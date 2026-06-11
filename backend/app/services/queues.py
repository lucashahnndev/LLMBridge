from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import ModelQueue, ModelQueueCandidate, QueueStrategy


@dataclass(frozen=True)
class ResolvedRouteCandidate:
    provider: str
    model_name: str
    queue_name: str | None = None
    queue_id: int | None = None
    candidate_id: int | None = None

    @property
    def route(self) -> str:
        return f"{self.provider}/{self.model_name}"


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


def _apply_queue_sort(strategy: QueueStrategy, candidates: list[ModelQueueCandidate]) -> list[ModelQueueCandidate]:
    active_candidates = [candidate for candidate in candidates if candidate.is_active]
    if strategy == QueueStrategy.LATENCY:
        return sorted(
            active_candidates,
            key=lambda candidate: (
                candidate.avg_latency_ms,
                -candidate.score,
                candidate.position,
                candidate.id,
            ),
        )
    if strategy == QueueStrategy.SMART:
        # Lower score means healthier and faster, so smarter queues prefer the
        # smallest score first and demote repeated failures over time.
        return sorted(
            active_candidates,
            key=lambda candidate: (
                candidate.score,
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
            -candidate.score,
            candidate.failure_count,
            candidate.id,
        ),
    )


async def resolve_model_routes(session: AsyncSession, model: str) -> list[ResolvedRouteCandidate]:
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
        return [ResolvedRouteCandidate(provider=provider, model_name=model_name)]

    queue_name = parse_queue_name(model)
    queue = await get_model_queue_or_404(session, queue_name)
    if not queue.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Queue '{queue_name}' is disabled")

    sorted_candidates = _apply_queue_sort(queue.strategy, list(queue.candidates))
    if not sorted_candidates:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Queue '{queue_name}' has no active candidates")

    return [
        ResolvedRouteCandidate(
            provider=candidate.provider,
            model_name=candidate.model_name,
            queue_name=queue.name,
            queue_id=queue.id,
            candidate_id=candidate.id,
        )
        for candidate in sorted_candidates
    ]


async def update_queue_candidate_on_success(
    session: AsyncSession,
    candidate: ModelQueueCandidate,
    latency_ms: float,
) -> None:
    now = datetime.now(timezone.utc)
    candidate.last_used_at = now
    candidate.last_success_at = now
    candidate.success_count = candidate.success_count + 1
    candidate.score = _score_for_success(candidate, latency_ms)
    candidate.avg_latency_ms = (
        latency_ms if candidate.success_count <= 1 else ((candidate.avg_latency_ms * (candidate.success_count - 1)) + latency_ms) / candidate.success_count
    )
    await session.commit()


async def update_queue_candidate_on_failure(
    session: AsyncSession,
    candidate: ModelQueueCandidate,
    status_code: int,
    latency_ms: float,
    error_message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    candidate.last_used_at = now
    candidate.last_error_at = now
    candidate.failure_count = candidate.failure_count + 1
    candidate.score = candidate.score + _score_for_failure(status_code, error_message)
    candidate.avg_latency_ms = (
        latency_ms if candidate.success_count + candidate.failure_count <= 1 else ((candidate.avg_latency_ms * max(candidate.success_count + candidate.failure_count - 1, 0)) + latency_ms) / (candidate.success_count + candidate.failure_count)
    )
    await session.commit()
