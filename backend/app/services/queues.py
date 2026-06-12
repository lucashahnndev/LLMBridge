from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from backend.app.database.models import ModelQueue, ModelQueueCandidate, QueueStrategy
from backend.app.services.availability import summarize_provider_route_availability


@dataclass(frozen=True)
class ResolvedRouteCandidate:
    provider: str
    model_name: str
    queue_name: str | None = None
    queue_id: int | None = None
    candidate_id: int | None = None
    provider_key_id: int | None = None
    provider_key_name: str | None = None

    @property
    def route(self) -> str:
        return f"{self.provider}/{self.model_name}"


@dataclass
class RouteMaterializationSummary:
    eligible_count: int = 0
    cooldown_count: int = 0
    disabled_count: int = 0
    blocked_count: int = 0
    recoverable_cooldowns: int = 0
    structural_unavailable_count: int = 0
    missing_pool_count: int = 0
    smallest_cooldown_until: datetime | None = None

    def merge(self, other: "RouteMaterializationSummary") -> None:
        self.eligible_count += other.eligible_count
        self.cooldown_count += other.cooldown_count
        self.disabled_count += other.disabled_count
        self.blocked_count += other.blocked_count
        self.recoverable_cooldowns += other.recoverable_cooldowns
        self.structural_unavailable_count += other.structural_unavailable_count
        self.missing_pool_count += other.missing_pool_count
        if other.smallest_cooldown_until is not None:
            if self.smallest_cooldown_until is None or other.smallest_cooldown_until < self.smallest_cooldown_until:
                self.smallest_cooldown_until = other.smallest_cooldown_until


@dataclass(frozen=True)
class ResolvedRouteSnapshot:
    routes: list[ResolvedRouteCandidate]
    summary: RouteMaterializationSummary
    route_kind: str
    requested_model: str
    queue_name: str | None = None


def is_queue_route(model: str) -> bool:
    return model.startswith("queue/")


def parse_queue_name(model: str) -> str:
    if not is_queue_route(model):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="queue routes must use queue/{queue-name}",
        )
    queue_name = model.split("/", 1)[1].strip()
    if not queue_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="queue routes must use queue/{queue-name}",
        )
    return queue_name


async def get_model_queue_or_404(session: AsyncSession, queue_name: str) -> ModelQueue:
    result = await session.execute(
        select(ModelQueue)
        .options(selectinload(ModelQueue.candidates))
        .where(ModelQueue.name == queue_name)
    )
    queue = result.scalar_one_or_none()
    if queue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Queue '{queue_name}' not found")
    return queue


def _score_for_success(candidate: ModelQueueCandidate, latency_ms: float) -> float:
    latency_bonus = max(0.1, min(1.0, 1.0 - (latency_ms / 5000.0)))
    return candidate.score - latency_bonus


def _score_for_failure(status_code: int, error_message: str | None = None) -> float:
    lowered = error_message.lower() if error_message else ""
    if status_code == status.HTTP_404_NOT_FOUND or any(
        keyword in lowered
        for keyword in ("not found", "not supported", "unsupported", "unknown model", "model unavailable")
    ):
        return 18.0
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return 8.0
    if status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        return 10.0
    if status_code >= 500:
        return 4.0
    return 2.0


def _latency_score(latency_ms: float) -> float:
    return max(0.0, min(1.0, latency_ms / 10000.0))


def _candidate_rank_value(candidate: ModelQueueCandidate) -> float:
    if candidate.final_rank == 0.0 and candidate.score != 0.0:
        return candidate.score
    return candidate.final_rank


def _refresh_candidate_rank(candidate: ModelQueueCandidate) -> None:
    candidate.final_rank = candidate.base_degradation + candidate.latency_score + candidate.error_score
    # Preserve the legacy field during the transition so older callers and UI
    # surfaces keep working while we move everything to final_rank.
    candidate.score = candidate.final_rank


def _apply_queue_sort(strategy: QueueStrategy, candidates: list[ModelQueueCandidate]) -> list[ModelQueueCandidate]:
    active_candidates = [candidate for candidate in candidates if candidate.is_active]
    if strategy == QueueStrategy.LATENCY:
        return sorted(
            active_candidates,
            key=lambda candidate: (
                candidate.avg_latency_ms,
                _candidate_rank_value(candidate),
                candidate.position,
                candidate.id,
            ),
        )
    if strategy == QueueStrategy.SMART:
        return sorted(
            active_candidates,
            key=lambda candidate: (
                _candidate_rank_value(candidate),
                candidate.failure_count,
                candidate.last_error_at or datetime.min.replace(tzinfo=timezone.utc),
                candidate.avg_latency_ms,
                candidate.position,
                candidate.id,
            ),
        )
    return sorted(
        active_candidates,
        key=lambda candidate: (
            candidate.position,
            _candidate_rank_value(candidate),
            candidate.failure_count,
            candidate.id,
        ),
    )


async def resolve_model_routes(session: AsyncSession, model: str) -> list[ResolvedRouteCandidate]:
    snapshot = await resolve_model_route_snapshot(session, model)
    return snapshot.routes


def _retry_after_seconds_from_summary(summary: RouteMaterializationSummary) -> int | None:
    if summary.smallest_cooldown_until is None:
        return None
    now = datetime.now(timezone.utc)
    return max(1, int((summary.smallest_cooldown_until - now).total_seconds() + 0.999999))


def _raise_for_exhausted_snapshot(snapshot: ResolvedRouteSnapshot) -> None:
    summary = snapshot.summary
    retry_after_seconds = _retry_after_seconds_from_summary(summary)
    if summary.recoverable_cooldowns > 0 and retry_after_seconds is not None:
        detail_message = (
            f"Queue '{snapshot.queue_name}' is temporarily exhausted by cooldown"
            if snapshot.route_kind == "queue"
            else f"Route '{snapshot.requested_model}' is temporarily exhausted by cooldown"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "cooldown_exhausted",
                "message": detail_message,
                "retry_after_seconds": retry_after_seconds,
            },
            headers={"Retry-After": str(retry_after_seconds)},
        )

    code = "route_unavailable" if snapshot.route_kind == "queue" else "pool_unavailable"
    detail_message = (
        f"Queue '{snapshot.queue_name}' has no structurally available routes"
        if snapshot.route_kind == "queue"
        else f"Route '{snapshot.requested_model}' has no structurally available provider keys"
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": code,
            "message": detail_message,
            "missing_pool_count": summary.missing_pool_count,
            "disabled_count": summary.disabled_count,
            "blocked_count": summary.blocked_count,
            "structural_unavailable_count": summary.structural_unavailable_count,
        },
    )


async def resolve_model_route_snapshot(session: AsyncSession, model: str) -> ResolvedRouteSnapshot:
    if not is_queue_route(model):
        if "/" not in model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model must use the provider/model-name format",
            )
        provider, model_name = model.split("/", 1)
        if not provider or not model_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model must use the provider/model-name format",
            )
        availability = await summarize_provider_route_availability(
            session,
            provider=provider,
            model_name=model_name,
        )
        summary = RouteMaterializationSummary(**availability.summary)
        routes = [
            ResolvedRouteCandidate(
                provider=provider,
                model_name=model_name,
                provider_key_id=provider_key.id,
                provider_key_name=provider_key.name,
            )
            for provider_key in availability.eligible_keys
        ]
        snapshot = ResolvedRouteSnapshot(
            routes=routes,
            summary=summary,
            route_kind="provider",
            requested_model=model,
            queue_name=None,
        )
        if not routes:
            _raise_for_exhausted_snapshot(snapshot)
        return snapshot

    queue_name = parse_queue_name(model)
    queue = await get_model_queue_or_404(session, queue_name)
    if not queue.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Queue '{queue_name}' is disabled")

    sorted_candidates = _apply_queue_sort(queue.strategy, list(queue.candidates))
    if not sorted_candidates:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Queue '{queue_name}' has no active candidates")

    summary = RouteMaterializationSummary()
    resolved_routes: list[ResolvedRouteCandidate] = []
    for candidate in sorted_candidates:
        availability = await summarize_provider_route_availability(
            session,
            provider=candidate.provider,
            model_name=candidate.model_name,
        )
        summary.merge(RouteMaterializationSummary(**availability.summary))
        if availability.eligible_keys:
            resolved_routes.extend(
                [
                    ResolvedRouteCandidate(
                        provider=candidate.provider,
                        model_name=candidate.model_name,
                        queue_name=queue.name,
                        queue_id=queue.id,
                        candidate_id=candidate.id,
                        provider_key_id=provider_key.id,
                        provider_key_name=provider_key.name,
                    )
                    for provider_key in availability.eligible_keys
                ]
            )
            continue

    snapshot = ResolvedRouteSnapshot(
        routes=resolved_routes,
        summary=summary,
        route_kind="queue",
        requested_model=model,
        queue_name=queue.name,
    )
    if not resolved_routes:
        _raise_for_exhausted_snapshot(snapshot)
    return snapshot


async def update_queue_candidate_on_success(
    session: AsyncSession,
    candidate: ModelQueueCandidate,
    latency_ms: float,
) -> None:
    from backend.app.services.classifier import RouteClassificationEvent, dispatch_route_classification_event

    now = datetime.now(timezone.utc)
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=candidate.provider,
            model_name=candidate.model_name,
            success=True,
            status_code=200,
            latency_ms=latency_ms,
            started_at=now,
            finished_at=now,
            candidate_id=candidate.id,
            route_kind="queue",
            queue_name=candidate.queue.name if candidate.queue is not None else None,
        ),
        swallow_errors=True,
    )


async def update_queue_candidate_on_failure(
    session: AsyncSession,
    candidate: ModelQueueCandidate,
    status_code: int,
    latency_ms: float,
    error_message: str | None = None,
) -> None:
    from backend.app.services.classifier import RouteClassificationEvent, dispatch_route_classification_event

    now = datetime.now(timezone.utc)
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=candidate.provider,
            model_name=candidate.model_name,
            success=False,
            status_code=status_code,
            latency_ms=latency_ms,
            started_at=now,
            finished_at=now,
            candidate_id=candidate.id,
            route_kind="queue",
            queue_name=candidate.queue.name if candidate.queue is not None else None,
            error_message=error_message,
        ),
        swallow_errors=True,
    )
