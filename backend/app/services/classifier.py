from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import KeyStatus, ModelQueueCandidate, ProviderKey
from backend.app.services.availability import (
    apply_route_block,
    apply_route_cooldown,
    get_or_create_provider_key_route_state,
    mark_route_finished,
)
from backend.app.services.route_materializer import schedule_route_materializer_refresh_all
from backend.app.services.records import ensure_utc_datetime
from backend.app.services.retry_parser import parse_retry_cooldown


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteClassificationEvent:
    provider: str
    model_name: str
    success: bool
    status_code: int
    latency_ms: float
    started_at: datetime
    finished_at: datetime
    key_id: int | None = None
    candidate_id: int | None = None
    route_kind: str = "provider"
    queue_name: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_headers: dict[str, str] | None = None
    response_body_preview: dict[str, object] | list[object] | str | None = None
    streaming: bool = False
    retry_hint_seconds: int | float | None = None
    exception_class: str | None = None


def _latency_score(latency_ms: float) -> float:
    return max(0.0, min(1.0, latency_ms / 10000.0))


def _provider_model_failure_weight(event: RouteClassificationEvent) -> float:
    lowered = (event.error_message or "").lower()
    if event.status_code == 404 and any(
        keyword in lowered
        for keyword in ("not found", "not supported", "unsupported", "unknown model", "model unavailable")
    ):
        return 18.0
    if event.status_code >= 500:
        return 4.0
    return 0.0


def _is_provider_model_404(event: RouteClassificationEvent) -> bool:
    lowered = (event.error_message or "").lower()
    return event.status_code == 404 and any(
        keyword in lowered
        for keyword in ("not found", "not supported", "unsupported", "unknown model", "model unavailable")
    )


def _is_route_access_404(event: RouteClassificationEvent) -> bool:
    return event.status_code == 404 and not _is_provider_model_404(event)


def _is_billing_forbidden(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(keyword in lowered for keyword in ("billing", "payment", "quota", "plan"))


async def _update_candidate_for_success(session: AsyncSession, candidate: ModelQueueCandidate, latency_ms: float, event_time: datetime) -> None:
    candidate.last_used_at = event_time
    candidate.last_success_at = event_time
    candidate.success_count = candidate.success_count + 1
    candidate.avg_latency_ms = (
        latency_ms
        if candidate.success_count <= 1
        else ((candidate.avg_latency_ms * (candidate.success_count - 1)) + latency_ms) / candidate.success_count
    )
    candidate.latency_score = _latency_score(candidate.avg_latency_ms)
    candidate.error_score = max(0.0, candidate.error_score - max(0.1, min(1.0, 1.0 - (latency_ms / 5000.0))))
    candidate.final_rank = candidate.base_degradation + candidate.latency_score + candidate.error_score
    candidate.score = candidate.final_rank
    await session.flush()


async def _update_candidate_for_failure(
    session: AsyncSession,
    candidate: ModelQueueCandidate,
    event: RouteClassificationEvent,
) -> None:
    failure_weight = _provider_model_failure_weight(event)
    candidate.last_used_at = event.finished_at
    candidate.last_error_at = event.finished_at
    if failure_weight <= 0.0:
        await session.flush()
        return

    candidate.failure_count = candidate.failure_count + 1
    total_observations = candidate.success_count + candidate.failure_count
    candidate.avg_latency_ms = (
        event.latency_ms
        if total_observations <= 1
        else ((candidate.avg_latency_ms * max(total_observations - 1, 0)) + event.latency_ms) / total_observations
    )
    candidate.latency_score = _latency_score(candidate.avg_latency_ms)
    candidate.error_score = candidate.error_score + failure_weight
    candidate.final_rank = candidate.base_degradation + candidate.latency_score + candidate.error_score
    candidate.score = candidate.final_rank
    await session.flush()


def _parse_event_retry(event: RouteClassificationEvent):
    if event.retry_hint_seconds is not None:
        delay = float(event.retry_hint_seconds)

        class RetryResult:
            retry_after_seconds = delay
            cooldown_until = (ensure_utc_datetime(event.finished_at) or datetime.now(timezone.utc)) + timedelta(seconds=delay)

        return RetryResult()

    import httpx

    headers = httpx.Headers(event.response_headers or {})
    return parse_retry_cooldown(
        headers,
        body=event.response_body_preview,
        provider=event.provider,
        now=ensure_utc_datetime(event.finished_at),
    )


async def classify_route_classification_event(session: AsyncSession, event: RouteClassificationEvent) -> None:
    settings = get_settings()
    finished_at = ensure_utc_datetime(event.finished_at) or datetime.now(timezone.utc)
    provider_key = await session.get(ProviderKey, event.key_id) if event.key_id is not None else None
    route_state = None
    if provider_key is not None:
        route_state = await get_or_create_provider_key_route_state(
            session,
            provider_key=provider_key,
            model_name=event.model_name,
        )
        mark_route_finished(route_state, now=finished_at)

    candidate = await session.get(ModelQueueCandidate, event.candidate_id) if event.candidate_id is not None else None

    if event.success:
        if route_state is not None:
            route_state.cooldown_until = None
            if not route_state.disabled:
                route_state.blocked_until = None
            route_state.last_used_at = finished_at
        if provider_key is not None and provider_key.status != KeyStatus.ACTIVE:
            provider_key.status = KeyStatus.ACTIVE
            provider_key.blocked_until = None
            provider_key.failure_count = 0
        if candidate is not None:
            await _update_candidate_for_success(session, candidate, event.latency_ms, finished_at)
        await session.commit()
        schedule_route_materializer_refresh_all()
        return

    retry_result = _parse_event_retry(event)

    if event.status_code == 429:
        if route_state is not None:
            delay = (
                retry_result.retry_after_seconds
                if retry_result is not None
                else float(settings.key_cooldown_seconds)
            )
            apply_route_cooldown(route_state, delay_seconds=delay, now=finished_at)
        await session.commit()
        schedule_route_materializer_refresh_all()
        return

    if event.status_code in {401, 403} and provider_key is not None and route_state is not None:
        provider_key.failure_count = provider_key.failure_count + 1
        provider_key.blocked_until = None
        if event.status_code == 401:
            provider_key.status = KeyStatus.INVALID
            apply_route_block(route_state, disabled=True, disabled_reason="unauthorized")
        else:
            if _is_billing_forbidden(event.error_message or ""):
                provider_key.status = KeyStatus.SUSPENDED_BILLING
                apply_route_block(route_state, disabled=True, disabled_reason="billing")
            else:
                provider_key.status = KeyStatus.INVALID
                apply_route_block(route_state, disabled=True, disabled_reason="forbidden")
        await session.commit()
        schedule_route_materializer_refresh_all()
        return

    if _is_route_access_404(event) and route_state is not None:
        apply_route_block(route_state, disabled=True, disabled_reason="not_found")
        await session.commit()
        schedule_route_materializer_refresh_all()
        return

    if event.status_code == 400:
        if route_state is not None:
            route_state.last_used_at = finished_at
        await session.commit()
        schedule_route_materializer_refresh_all()
        return

    if event.status_code >= 500 and route_state is not None and retry_result is not None:
        apply_route_cooldown(route_state, delay_seconds=retry_result.retry_after_seconds, now=finished_at)

    if candidate is not None:
        await _update_candidate_for_failure(session, candidate, event)

    await session.commit()
    schedule_route_materializer_refresh_all()


async def dispatch_route_classification_event(
    session: AsyncSession,
    event: RouteClassificationEvent,
    *,
    swallow_errors: bool = True,
) -> bool:
    try:
        await classify_route_classification_event(session, event)
        return True
    except Exception:
        if swallow_errors:
            logger.exception(
                "Route classification failed",
                extra={
                    "provider": event.provider,
                    "model_name": event.model_name,
                    "key_id": event.key_id,
                    "candidate_id": event.candidate_id,
                    "status_code": event.status_code,
                },
            )
            return False
        raise
