from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import KeyStatus, ProviderKey, ProviderKeyRouteState
from backend.app.drivers import get_provider_driver
from backend.app.services.records import ensure_utc_datetime


def normalize_provider_route_model_name(provider: str, model_name: str) -> str:
    cleaned_provider = provider.strip()
    cleaned_model_name = model_name.strip()
    try:
        driver = get_provider_driver(cleaned_provider)
    except KeyError:
        return cleaned_model_name

    resolve_model_name = getattr(driver, "resolve_model_name", None)
    if not callable(resolve_model_name):
        return cleaned_model_name
    return resolve_model_name(cleaned_model_name)


def _route_state_rank_value(route_state: ProviderKeyRouteState | None) -> tuple[int, datetime, datetime]:
    if route_state is None:
        return (0.0, 0, datetime.min.replace(tzinfo=timezone.utc))
    return (
        route_state.in_flight_count,
        ensure_utc_datetime(route_state.last_used_at) or datetime.min.replace(tzinfo=timezone.utc),
        ensure_utc_datetime(route_state.updated_at) or datetime.min.replace(tzinfo=timezone.utc),
    )


async def get_provider_key_route_state(
    session: AsyncSession,
    *,
    provider_key_id: int,
    provider: str,
    model_name: str,
) -> ProviderKeyRouteState | None:
    normalized_model_name = normalize_provider_route_model_name(provider, model_name)
    result = await session.execute(
        select(ProviderKeyRouteState).where(
            ProviderKeyRouteState.provider_key_id == provider_key_id,
            ProviderKeyRouteState.provider == provider,
            ProviderKeyRouteState.model_name == normalized_model_name,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_provider_key_route_state(
    session: AsyncSession,
    *,
    provider_key: ProviderKey,
    model_name: str,
) -> ProviderKeyRouteState:
    normalized_model_name = normalize_provider_route_model_name(provider_key.provider, model_name)
    state = await get_provider_key_route_state(
        session,
        provider_key_id=provider_key.id,
        provider=provider_key.provider,
        model_name=normalized_model_name,
    )
    if state is not None:
        return state

    state = ProviderKeyRouteState(
        provider_key_id=provider_key.id,
        provider=provider_key.provider,
        model_name=normalized_model_name,
    )
    session.add(state)
    await session.flush()
    return state


def route_state_is_eligible(
    state: ProviderKeyRouteState,
    *,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    if state.disabled:
        return False
    blocked_until = ensure_utc_datetime(state.blocked_until)
    if blocked_until is not None and blocked_until > current_time:
        return False
    cooldown_until = ensure_utc_datetime(state.cooldown_until)
    if cooldown_until is not None and cooldown_until > current_time:
        return False
    next_available_at = ensure_utc_datetime(state.next_available_at)
    if next_available_at is not None and next_available_at > current_time:
        return False
    soft_reserved_until = ensure_utc_datetime(state.soft_reserved_until)
    if soft_reserved_until is not None and soft_reserved_until > current_time:
        return False
    return True


def apply_route_cooldown(
    state: ProviderKeyRouteState,
    *,
    delay_seconds: float,
    now: datetime | None = None,
) -> ProviderKeyRouteState:
    current_time = now or datetime.now(timezone.utc)
    cooldown_until = current_time + timedelta(seconds=max(delay_seconds, 0.0))
    existing = ensure_utc_datetime(state.cooldown_until)
    state.cooldown_until = max(existing or cooldown_until, cooldown_until)
    return state


def apply_route_block(
    state: ProviderKeyRouteState,
    *,
    blocked_until: datetime | None = None,
    disabled: bool = False,
    disabled_reason: str | None = None,
) -> ProviderKeyRouteState:
    if blocked_until is not None:
        current_block = ensure_utc_datetime(state.blocked_until)
        next_block = ensure_utc_datetime(blocked_until) or blocked_until
        state.blocked_until = max(current_block or next_block, next_block)
    if disabled:
        state.disabled = True
    if disabled_reason is not None:
        state.disabled_reason = disabled_reason
    return state


def mark_route_selected(
    state: ProviderKeyRouteState,
    *,
    now: datetime | None = None,
    soft_reservation_ms: int | None = None,
    next_available_delay_ms: int | None = None,
) -> ProviderKeyRouteState:
    current_time = now or datetime.now(timezone.utc)
    state.in_flight_count = max(0, state.in_flight_count) + 1
    state.last_used_at = current_time
    if soft_reservation_ms is not None and soft_reservation_ms > 0:
        state.soft_reserved_until = current_time + timedelta(milliseconds=soft_reservation_ms)
    if next_available_delay_ms is not None and next_available_delay_ms > 0:
        state.next_available_at = current_time + timedelta(milliseconds=next_available_delay_ms)
    return state


def mark_route_finished(
    state: ProviderKeyRouteState,
    *,
    now: datetime | None = None,
    next_available_delay_ms: int | None = None,
) -> ProviderKeyRouteState:
    current_time = now or datetime.now(timezone.utc)
    state.in_flight_count = max(0, state.in_flight_count - 1)
    state.soft_reserved_until = None
    if next_available_delay_ms is not None and next_available_delay_ms > 0:
        state.next_available_at = current_time + timedelta(milliseconds=next_available_delay_ms)
    return state


async def list_balanced_provider_keys_for_route(
    session: AsyncSession,
    *,
    provider: str,
    model_name: str,
    now: datetime | None = None,
) -> list[ProviderKey]:
    availability = await summarize_provider_route_availability(
        session,
        provider=provider,
        model_name=model_name,
        now=now,
    )
    return availability.eligible_keys


@dataclass(frozen=True)
class ProviderRouteAvailability:
    eligible_keys: list[ProviderKey]
    eligible_states: dict[int, ProviderKeyRouteState | None]
    summary: dict[str, object]


async def summarize_provider_route_availability(
    session: AsyncSession,
    *,
    provider: str,
    model_name: str,
    now: datetime | None = None,
) -> ProviderRouteAvailability:
    current_time = now or datetime.now(timezone.utc)
    normalized_model_name = normalize_provider_route_model_name(provider, model_name)
    provider_keys_result = await session.execute(select(ProviderKey).where(ProviderKey.provider == provider))
    provider_keys = list(provider_keys_result.scalars().all())
    if not provider_keys:
        return ProviderRouteAvailability(
            eligible_keys=[],
            eligible_states={},
            summary={
                "eligible_count": 0,
                "cooldown_count": 0,
                "disabled_count": 0,
                "blocked_count": 0,
                "recoverable_cooldowns": 0,
                "smallest_cooldown_until": None,
                "structural_unavailable_count": 1,
                "missing_pool_count": 1,
            },
        )

    key_ids = [provider_key.id for provider_key in provider_keys]
    route_states_result = await session.execute(
        select(ProviderKeyRouteState).where(
            ProviderKeyRouteState.provider == provider,
            ProviderKeyRouteState.model_name == normalized_model_name,
            ProviderKeyRouteState.provider_key_id.in_(key_ids),
        )
    )
    route_state_by_key_id = {
        route_state.provider_key_id: route_state
        for route_state in route_states_result.scalars().all()
    }

    eligible_rows: list[tuple[float, int, datetime, int, ProviderKey]] = []
    eligible_states: dict[int, ProviderKeyRouteState | None] = {}
    cooldown_count = 0
    disabled_count = 0
    blocked_count = 0
    recoverable_cooldowns = 0
    structural_unavailable_count = 0
    smallest_cooldown_until: datetime | None = None

    for provider_key in provider_keys:
        route_state = route_state_by_key_id.get(provider_key.id)
        if provider_key.status in {KeyStatus.INVALID, KeyStatus.SUSPENDED_BILLING}:
            disabled_count += 1
            structural_unavailable_count += 1
            continue

        key_blocked_until = ensure_utc_datetime(provider_key.blocked_until)
        if key_blocked_until is not None and key_blocked_until > current_time:
            blocked_count += 1
            structural_unavailable_count += 1
            continue

        if route_state is not None:
            if route_state.disabled:
                disabled_count += 1
                structural_unavailable_count += 1
                continue

            route_blocked_until = ensure_utc_datetime(route_state.blocked_until)
            if route_blocked_until is not None and route_blocked_until > current_time:
                blocked_count += 1
                structural_unavailable_count += 1
                continue

            cooldown_until = ensure_utc_datetime(route_state.cooldown_until)
            if cooldown_until is not None and cooldown_until > current_time:
                cooldown_count += 1
                recoverable_cooldowns += 1
                if smallest_cooldown_until is None or cooldown_until < smallest_cooldown_until:
                    smallest_cooldown_until = cooldown_until
                continue

        eligible_rows.append(
            (
                _route_state_rank_value(route_state)[0],
                _route_state_rank_value(route_state)[1],
                ensure_utc_datetime(provider_key.updated_at) or datetime.min.replace(tzinfo=timezone.utc),
                provider_key.id,
                provider_key,
            )
        )
        eligible_states[provider_key.id] = route_state

    eligible_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    eligible_keys = [provider_key for *_, provider_key in eligible_rows]
    return ProviderRouteAvailability(
        eligible_keys=eligible_keys,
        eligible_states=eligible_states,
        summary={
            "eligible_count": len(eligible_keys),
            "cooldown_count": cooldown_count,
            "disabled_count": disabled_count,
            "blocked_count": blocked_count,
            "recoverable_cooldowns": recoverable_cooldowns,
            "smallest_cooldown_until": smallest_cooldown_until,
            "structural_unavailable_count": structural_unavailable_count,
            "missing_pool_count": 0,
        },
    )
