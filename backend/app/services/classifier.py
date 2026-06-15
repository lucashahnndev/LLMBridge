from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import KeyStatus, ProviderKey, ProviderKeyRouteState, ProviderModelRouteScore
from backend.app.services.availability import (
    apply_route_block,
    apply_route_cooldown,
    get_or_create_provider_key_route_state,
    normalize_provider_route_model_name,
    mark_route_finished,
)
from backend.app.services.route_materializer import (
    apply_materialized_route_unavailability,
    schedule_route_materializer_refresh_models,
)
from backend.app.services.records import ensure_utc_datetime
from backend.app.services.retry_parser import parse_retry_cooldown


logger = logging.getLogger(__name__)

MODEL_NOT_FOUND_ERROR_WEIGHT = 0.85
TRANSIENT_UPSTREAM_ERROR_WEIGHT = 0.35
SUCCESS_RECOVERY_FLOOR = 0.03
SUCCESS_RECOVERY_CEILING = 0.18


def _schedule_event_snapshot_refresh(event: RouteClassificationEvent) -> None:
    targets = [f"{event.provider}/{event.model_name}"]
    if event.route_kind == "queue" and event.queue_name:
        targets.append(f"queue/{event.queue_name}")
    schedule_route_materializer_refresh_models(targets)


def _patch_event_snapshots_for_unavailability(
    event: RouteClassificationEvent,
    *,
    reason: str,
    cooldown_until: datetime | None = None,
) -> None:
    if reason not in {"cooldown", "blocked", "disabled"}:
        return
    apply_materialized_route_unavailability(
        provider=event.provider,
        model_name=event.model_name,
        provider_key_id=event.key_id,
        reason=reason,
        cooldown_until=cooldown_until,
    )


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


def _refresh_provider_model_score_rank(score_row: ProviderModelRouteScore) -> None:
    score_row.final_rank = score_row.latency_score + score_row.error_score
    score_row.score = score_row.final_rank


async def _get_or_create_provider_model_score(
    session: AsyncSession,
    *,
    provider: str,
    model_name: str,
) -> ProviderModelRouteScore:
    normalized_model_name = normalize_provider_route_model_name(provider, model_name)
    result = await session.execute(
        select(ProviderModelRouteScore).where(
            ProviderModelRouteScore.provider == provider,
            ProviderModelRouteScore.model_name == normalized_model_name,
        )
    )
    score_row = result.scalar_one_or_none()
    if score_row is not None:
        return score_row

    score_row = ProviderModelRouteScore(provider=provider, model_name=normalized_model_name)
    session.add(score_row)
    await session.flush()
    return score_row


def _update_provider_model_score_for_success(
    score_row: ProviderModelRouteScore,
    latency_ms: float,
    event_time: datetime,
) -> None:
    score_row.last_success_at = event_time
    score_row.success_count = score_row.success_count + 1
    score_row.avg_latency_ms = (
        latency_ms
        if score_row.success_count <= 1
        else ((score_row.avg_latency_ms * (score_row.success_count - 1)) + latency_ms) / score_row.success_count
    )
    score_row.latency_score = _latency_score(score_row.avg_latency_ms)
    recovery = max(SUCCESS_RECOVERY_FLOOR, min(SUCCESS_RECOVERY_CEILING, 0.18 - (latency_ms / 10000.0)))
    score_row.error_score = max(0.0, score_row.error_score - recovery)
    _refresh_provider_model_score_rank(score_row)


def _update_provider_model_score_for_failure(
    score_row: ProviderModelRouteScore,
    event: RouteClassificationEvent,
) -> None:
    failure_weight = _provider_model_failure_weight(event)
    score_row.last_error_at = event.finished_at
    if failure_weight <= 0.0:
        return

    score_row.failure_count = score_row.failure_count + 1
    total_observations = score_row.success_count + score_row.failure_count
    score_row.avg_latency_ms = (
        event.latency_ms
        if total_observations <= 1
        else ((score_row.avg_latency_ms * max(total_observations - 1, 0)) + event.latency_ms) / total_observations
    )
    score_row.latency_score = _latency_score(score_row.avg_latency_ms)
    score_row.error_score = score_row.error_score + failure_weight
    _refresh_provider_model_score_rank(score_row)


def _provider_model_failure_weight(event: RouteClassificationEvent) -> float:
    lowered = (event.error_message or "").lower()
    if event.status_code == 404 and any(
        keyword in lowered
        for keyword in ("not found", "not supported", "unsupported", "unknown model", "model unavailable")
    ):
        return MODEL_NOT_FOUND_ERROR_WEIGHT
    if event.status_code >= 500:
        return TRANSIENT_UPSTREAM_ERROR_WEIGHT
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
    provider_model_score = await _get_or_create_provider_model_score(
        session,
        provider=event.provider,
        model_name=event.model_name,
    )
    if provider_key is not None:
        route_state = await get_or_create_provider_key_route_state(
            session,
            provider_key=provider_key,
            model_name=event.model_name,
        )
        mark_route_finished(
            route_state,
            now=finished_at,
            next_available_delay_ms=settings.key_next_available_delay_ms,
        )

    if event.success:
        if route_state is not None:
            route_state.cooldown_until = None
            if not route_state.disabled:
                route_state.blocked_until = None
        if provider_model_score is not None:
            _update_provider_model_score_for_success(provider_model_score, event.latency_ms, finished_at)
        if provider_key is not None and provider_key.status != KeyStatus.ACTIVE:
            provider_key.status = KeyStatus.ACTIVE
            provider_key.blocked_until = None
            provider_key.failure_count = 0
        await session.commit()
        _schedule_event_snapshot_refresh(event)
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
        _patch_event_snapshots_for_unavailability(
            event,
            reason="cooldown",
            cooldown_until=ensure_utc_datetime(route_state.cooldown_until) if route_state is not None else None,
        )
        _schedule_event_snapshot_refresh(event)
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
        _patch_event_snapshots_for_unavailability(event, reason="disabled")
        _schedule_event_snapshot_refresh(event)
        return

    if _is_provider_model_404(event) and provider_model_score is not None:
        _update_provider_model_score_for_failure(provider_model_score, event)
        if route_state is not None:
            apply_route_block(route_state, disabled=True, disabled_reason="not_found")
        await session.commit()
        _patch_event_snapshots_for_unavailability(event, reason="disabled")
        _schedule_event_snapshot_refresh(event)
        return

    if _is_route_access_404(event) and route_state is not None:
        apply_route_block(route_state, disabled=True, disabled_reason="not_found")
        await session.commit()
        _patch_event_snapshots_for_unavailability(event, reason="disabled")
        _schedule_event_snapshot_refresh(event)
        return

    if event.status_code == 400:
        if route_state is not None:
            route_state.last_used_at = finished_at
        await session.commit()
        _schedule_event_snapshot_refresh(event)
        return

    if event.status_code >= 500 and provider_model_score is not None:
        if retry_result is not None and route_state is not None:
            apply_route_cooldown(route_state, delay_seconds=retry_result.retry_after_seconds, now=finished_at)
        _update_provider_model_score_for_failure(provider_model_score, event)

    await session.commit()
    if event.status_code >= 500 and route_state is not None and retry_result is not None:
        _patch_event_snapshots_for_unavailability(
            event,
            reason="cooldown",
            cooldown_until=ensure_utc_datetime(route_state.cooldown_until),
        )
    _schedule_event_snapshot_refresh(event)


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
