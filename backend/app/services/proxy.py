from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import AppToken, KeyStatus, ModelQueueCandidate, ProviderKey, ProviderKeyModelCooldown, UsageLog
from backend.app.database.session import get_session
from backend.app.drivers import get_provider_driver
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.alerts import (
    format_provider_pool_exhausted_alert,
    format_proxy_failure_alert,
    format_queue_exhausted_alert,
    send_telegram_alert,
)
from backend.app.services.crypto import decrypt_text
from backend.app.services.queues import (
    ResolvedRouteCandidate,
    is_queue_route,
    parse_queue_name,
    resolve_model_routes,
    update_queue_candidate_on_failure,
    update_queue_candidate_on_success,
)
from backend.app.services.records import ensure_utc_datetime


security = HTTPBearer(auto_error=False)


async def get_app_token(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AppToken:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing app token")
    token = credentials.credentials
    result = await session.execute(
        select(AppToken).where(AppToken.token == token, AppToken.is_active.is_(True))
    )
    app_token = result.scalar_one_or_none()
    if app_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive app token")
    return app_token


async def require_app_token(app_token: Annotated[AppToken, Depends(get_app_token)]) -> AppToken:
    return app_token


def parse_model_identifier(model: str) -> tuple[str, str]:
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
    return provider, model_name


def parse_retry_after_seconds(headers: httpx.Headers) -> int | None:
    retry_after = headers.get("retry-after")
    if retry_after:
        retry_after = retry_after.strip()
        if retry_after.isdigit():
            return max(0, int(retry_after))
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = int((retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
            return max(0, seconds)
        except (TypeError, ValueError, IndexError):
            pass

    reset_after = headers.get("x-ratelimit-reset-after")
    if reset_after:
        try:
            return max(0, int(float(reset_after)))
        except ValueError:
            pass

    reset_at = headers.get("x-ratelimit-reset")
    if reset_at:
        try:
            reset_dt = datetime.fromtimestamp(float(reset_at), tz=timezone.utc)
            seconds = int((reset_dt - datetime.now(timezone.utc)).total_seconds())
            return max(0, seconds)
        except ValueError:
            pass

    return None


async def get_eligible_provider_keys(
    session: AsyncSession,
    provider: str,
    model_name: str,
) -> list[ProviderKey]:
    now = datetime.now(timezone.utc)
    provider_result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider == provider,
            ~ProviderKey.status.in_([KeyStatus.INVALID, KeyStatus.SUSPENDED_BILLING]),
        )
    )
    provider_keys = list(provider_result.scalars().all())
    if not provider_keys:
        return []

    cooldown_result = await session.execute(
        select(ProviderKeyModelCooldown).where(
            ProviderKeyModelCooldown.model_name == model_name,
            ProviderKeyModelCooldown.provider_key_id.in_([provider_key.id for provider_key in provider_keys]),
        )
    )
    cooldown_by_key_id = {row.provider_key_id: row for row in cooldown_result.scalars().all()}

    eligible: list[tuple[int, int, datetime, int, ProviderKey]] = []
    for provider_key in provider_keys:
        cooldown = cooldown_by_key_id.get(provider_key.id)
        blocked_until = ensure_utc_datetime(cooldown.blocked_until) if cooldown else None
        if blocked_until is not None and blocked_until > now:
            continue
        model_penalty = cooldown.failure_count if cooldown else 0
        eligible.append(
            (
                model_penalty,
                provider_key.failure_count,
                ensure_utc_datetime(provider_key.updated_at) or datetime.min.replace(tzinfo=timezone.utc),
                provider_key.id,
                provider_key,
            )
        )

    eligible.sort(
        key=lambda item: (item[0], item[1], item[2], item[3])
    )
    return [provider_key for *_, provider_key in eligible]


def extract_usage_metrics(response_json: dict[str, object]) -> tuple[int, int, int]:
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return prompt_tokens, completion_tokens, total_tokens


def is_tool_calling_payload(payload: dict[str, object]) -> bool:
    tools = payload.get("tools")
    tool_choice = payload.get("tool_choice")
    function_call = payload.get("function_call")
    legacy_functions = payload.get("functions")
    return bool(tools) or tool_choice is not None or function_call is not None or legacy_functions is not None


def is_tool_calling_response(response_json: dict[str, object] | list[object] | str | None) -> bool:
    if isinstance(response_json, dict):
        choices = response_json.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    tool_calls = message.get("tool_calls")
                    if isinstance(tool_calls, list) and tool_calls:
                        return True
                    if message.get("function_call") is not None:
                        return True
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    if isinstance(delta.get("tool_calls"), list) and delta["tool_calls"]:
                        return True
                    if delta.get("function_call") is not None:
                        return True
        return False
    if isinstance(response_json, list):
        return any(is_tool_calling_response(entry) for entry in response_json)
    return False


def coerce_response_body(response: httpx.Response) -> dict[str, object] | list[object] | str:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return {"detail": response.text}
    return response.json()


async def log_usage(
    session: AsyncSession,
    *,
    app_token_id: int,
    provider_key_id: int | None,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
    route_kind: str = "provider",
    queue_name: str | None = None,
    model_requested: str,
    provider_used: str,
    resolved_model: str | None = None,
    latency_ms: float,
    status_code: int,
    was_rotated: bool,
    tool_calling: bool = False,
    response_json: dict[str, object] | list[object] | str | None = None,
    error_message: str | None = None,
) -> None:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    if isinstance(response_json, dict):
        prompt_tokens, completion_tokens, total_tokens = extract_usage_metrics(response_json)

    usage_log = UsageLog(
        app_token_id=app_token_id,
        provider_key_id=provider_key_id,
        protocol_in=protocol_in,
        protocol_out=protocol_out,
        route_kind=route_kind,
        queue_name=queue_name,
        model_requested=model_requested,
        provider_used=provider_used,
        resolved_model=resolved_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        status_code=status_code,
        was_rotated=was_rotated,
        tool_calling=tool_calling,
        error_message=error_message,
    )
    session.add(usage_log)
    await session.commit()


async def _best_effort_send_alert(message: str) -> None:
    try:
        await send_telegram_alert(message)
    except Exception:
        return


def _extract_error_text(body: dict[str, object] | list[object] | str | None) -> str | dict[str, object] | list[object] | None:
    if body is None:
        return None
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return body
    detail = body.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return body


async def _send_resolution_alert(
    *,
    app_token: AppToken,
    requested_model: str,
    route_kind: str,
    queue_name: str | None,
    protocol_in: str,
    protocol_out: str,
    status_code: int,
    attempts: int,
    rotated: bool,
    tool_calling: bool,
    final_route: str | None,
    error: str | dict[str, object] | list[object] | None,
) -> None:
    alert_message = format_proxy_failure_alert(
        app_token_name=app_token.name,
        requested_model=requested_model,
        final_route=final_route,
        route_kind=route_kind,
        queue_name=queue_name,
        protocol_in=protocol_in,
        protocol_out=protocol_out,
        status_code=status_code,
        attempts=attempts,
        tool_calling=tool_calling,
        rotated=rotated,
        error=error,
    )
    await _best_effort_send_alert(alert_message)


async def mark_provider_key_success(session: AsyncSession, provider_key: ProviderKey) -> None:
    if provider_key.status != KeyStatus.ACTIVE or provider_key.failure_count != 0 or provider_key.blocked_until is not None:
        provider_key.status = KeyStatus.ACTIVE
        provider_key.blocked_until = None
        provider_key.failure_count = 0
        await session.commit()


async def mark_provider_key_model_failure(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
    retry_after_seconds: int | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    existing = await session.execute(
        select(ProviderKeyModelCooldown).where(
            ProviderKeyModelCooldown.provider_key_id == provider_key.id,
            ProviderKeyModelCooldown.model_name == model_name,
        )
    )
    cooldown = existing.scalar_one_or_none()
    blocked_until = now + timedelta(seconds=max(1, retry_after_seconds)) if retry_after_seconds is not None else now
    if cooldown is None:
        cooldown = ProviderKeyModelCooldown(
            provider_key_id=provider_key.id,
            model_name=model_name,
            blocked_until=blocked_until,
            failure_count=1,
        )
        session.add(cooldown)
    else:
        if retry_after_seconds is not None:
            cooldown.blocked_until = blocked_until
        cooldown.failure_count = cooldown.failure_count + 1
    await session.commit()


async def mark_provider_key_model_success(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
) -> None:
    existing = await session.execute(
        select(ProviderKeyModelCooldown).where(
            ProviderKeyModelCooldown.provider_key_id == provider_key.id,
            ProviderKeyModelCooldown.model_name == model_name,
        )
    )
    cooldown = existing.scalar_one_or_none()
    if cooldown is None:
        return
    if cooldown.failure_count <= 1:
        await session.delete(cooldown)
    else:
        cooldown.failure_count = cooldown.failure_count - 1
        if cooldown.failure_count <= 0 and ensure_utc_datetime(cooldown.blocked_until) <= datetime.now(timezone.utc):
            await session.delete(cooldown)
            await session.commit()
            return
    await session.commit()


async def mark_provider_key_model_soft_failure(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
) -> None:
    now = datetime.now(timezone.utc)
    existing = await session.execute(
        select(ProviderKeyModelCooldown).where(
            ProviderKeyModelCooldown.provider_key_id == provider_key.id,
            ProviderKeyModelCooldown.model_name == model_name,
        )
    )
    cooldown = existing.scalar_one_or_none()
    if cooldown is None:
        cooldown = ProviderKeyModelCooldown(
            provider_key_id=provider_key.id,
            model_name=model_name,
            blocked_until=now,
            failure_count=1,
        )
        session.add(cooldown)
    else:
        cooldown.failure_count = cooldown.failure_count + 1
        cooldown.blocked_until = max(ensure_utc_datetime(cooldown.blocked_until) or now, now)
    await session.commit()


async def mark_provider_key_auth_failed(session: AsyncSession, provider_key: ProviderKey, status_code: int, error_text: str) -> None:
    provider_key.failure_count = provider_key.failure_count + 1
    provider_key.blocked_until = None
    if status_code == status.HTTP_401_UNAUTHORIZED:
        provider_key.status = KeyStatus.INVALID
    elif status_code == status.HTTP_403_FORBIDDEN:
        lowered = error_text.lower()
        if any(keyword in lowered for keyword in ("billing", "payment", "quota", "plan")):
            provider_key.status = KeyStatus.SUSPENDED_BILLING
        else:
            provider_key.status = KeyStatus.INVALID
    await session.commit()


def format_rate_limit_message(provider: str) -> str:
    return f"Rate limit exhausted across eligible provider keys for provider '{provider}'"


def format_provider_pool_exhausted_message(
    provider: str,
    *,
    total: int,
    active: int,
    cooldown: int,
    invalid: int,
    next_retry_at: datetime | None = None,
) -> str:
    if total == 0:
        return f"No provider keys configured for provider '{provider}'"

    if active == 0 and cooldown > 0 and next_retry_at is not None:
        retry_at = next_retry_at.astimezone(timezone.utc).isoformat()
        return (
            f"All {total} provider keys for provider '{provider}' are cooling down "
            f"until {retry_at}"
        )

    return (
        f"No eligible provider keys available for provider '{provider}' "
        f"(total={total}, active={active}, cooldown={cooldown}, invalid={invalid})"
    )


async def build_provider_pool_exhausted_message(session: AsyncSession, provider: str, model_name: str) -> str:
    key_stmt = select(ProviderKey.status).where(ProviderKey.provider == provider)
    key_result = await session.execute(key_stmt)
    key_rows = key_result.all()
    total = len(key_rows)
    invalid = sum(1 for (status_value,) in key_rows if status_value in {KeyStatus.INVALID, KeyStatus.SUSPENDED_BILLING})
    valid = total - invalid

    cooldown_stmt = select(ProviderKeyModelCooldown.blocked_until).join(
        ProviderKey,
        ProviderKey.id == ProviderKeyModelCooldown.provider_key_id,
    ).where(
        ProviderKey.provider == provider,
        ProviderKeyModelCooldown.model_name == model_name,
    )
    cooldown_result = await session.execute(cooldown_stmt)
    now = datetime.now(timezone.utc)
    cooldown_until_values = [
        ensure_utc_datetime(blocked_until)
        for (blocked_until,) in cooldown_result.all()
        if ensure_utc_datetime(blocked_until) is not None and ensure_utc_datetime(blocked_until) > now
    ]
    model_cooldown_count = len(cooldown_until_values)
    next_retry_at = min(cooldown_until_values) if cooldown_until_values else None
    if total == 0:
        return format_provider_pool_exhausted_message(
            provider,
            total=0,
            active=0,
            cooldown=0,
            invalid=0,
            next_retry_at=None,
        )
    if valid - model_cooldown_count <= 0 and model_cooldown_count > 0 and next_retry_at is not None:
        retry_at = next_retry_at.astimezone(timezone.utc).isoformat()
        return (
            f"All {total} provider keys for provider '{provider}' are cooling down "
            f"for model '{model_name}' until {retry_at}"
        )
    return format_provider_pool_exhausted_message(
        provider,
        total=total,
        active=valid - model_cooldown_count,
        cooldown=model_cooldown_count,
        invalid=invalid,
        next_retry_at=next_retry_at,
    )


def should_rotate_to_next_key(status_code: int) -> bool:
    return status_code >= 400


def extract_failure_message(body: dict[str, object] | list[object] | str | None, fallback: str) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message
        return fallback
    if isinstance(body, list):
        for entry in body:
            extracted = extract_failure_message(entry, fallback)
            if extracted != fallback:
                return extracted
        return fallback
    if isinstance(body, str) and body.strip():
        return body
    return fallback


async def _proxy_chat_completion_for_route(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    route_model: str,
    *,
    requested_model: str | None = None,
    queue_name: str | None = None,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
) -> tuple[int, dict[str, object] | list[object] | str, float]:
    requested_model = requested_model or route_model
    provider, model_name = parse_model_identifier(route_model)
    try:
        driver = get_provider_driver(provider)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider '{provider}'") from exc
    resolve_model_name = getattr(driver, "resolve_model_name", None)
    resolved_model_name = resolve_model_name(model_name) if callable(resolve_model_name) else model_name
    resolved_route_model = f"{provider}/{resolved_model_name}"

    settings = get_settings()
    provider_keys = await get_eligible_provider_keys(session, provider, resolved_model_name)
    if not provider_keys:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await build_provider_pool_exhausted_message(session, provider, resolved_model_name),
        )

    request_payload = payload.model_dump(exclude_none=True, exclude={"model"})
    request_payload.update(payload.model_extra or {})
    route_kind = "queue" if queue_name else "provider"
    request_tool_calling = is_tool_calling_payload(request_payload)

    start_time = time.perf_counter()
    last_status_code = 502
    last_body: dict[str, object] | list[object] | str = {"detail": "Proxy request failed"}
    used_key: ProviderKey | None = None
    was_rotated = False

    timeout = httpx.Timeout(settings.proxy_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt_index, provider_key in enumerate(provider_keys):
            used_key = provider_key
            try:
                response = await driver.send_chat_completion(
                    client=client,
                    provider_token=decrypt_text(provider_key.encrypted_token),
                    normalized_payload=request_payload,
                    model_name=resolved_model_name,
                )
            except httpx.HTTPError as exc:
                failure_message = str(exc) or "Provider request failed"
                await mark_provider_key_model_soft_failure(session, provider_key, resolved_model_name)
                was_rotated = attempt_index > 0
                await log_usage(
                    session,
                    app_token_id=app_token.id,
                    provider_key_id=provider_key.id,
                    protocol_in=protocol_in,
                    protocol_out=protocol_out,
                    route_kind=route_kind,
                    queue_name=queue_name,
                    model_requested=requested_model,
                    provider_used=provider,
                    resolved_model=resolved_route_model,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    was_rotated=was_rotated,
                    tool_calling=request_tool_calling,
                    response_json={"detail": failure_message},
                    error_message=failure_message[:500],
                )
                if attempt_index + 1 < len(provider_keys):
                    continue
                last_status_code = status.HTTP_502_BAD_GATEWAY
                last_body = {"detail": failure_message}
                break

            body = coerce_response_body(response)
            last_status_code = response.status_code
            last_body = body
            was_rotated = attempt_index > 0

            failure_message = extract_failure_message(
                body,
                "Provider request failed",
            )

            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                retry_after_seconds = parse_retry_after_seconds(response.headers) or settings.key_cooldown_seconds
                await mark_provider_key_model_failure(session, provider_key, resolved_model_name, retry_after_seconds)
                if attempt_index + 1 < len(provider_keys):
                    was_rotated = True
                    continue
                break

            if response.status_code in {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            }:
                await mark_provider_key_auth_failed(session, provider_key, response.status_code, failure_message)
                if attempt_index + 1 < len(provider_keys):
                    was_rotated = True
                    continue
                break

            if 200 <= response.status_code < 300:
                await mark_provider_key_model_success(session, provider_key, resolved_model_name)
                await mark_provider_key_success(session, provider_key)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                body = driver.normalize_response_body(body, resolved_model_name)
                await log_usage(
                    session,
                    app_token_id=app_token.id,
                    provider_key_id=provider_key.id,
                    protocol_in=protocol_in,
                    protocol_out=protocol_out,
                    route_kind=route_kind,
                    queue_name=queue_name,
                    model_requested=requested_model,
                    provider_used=provider,
                    resolved_model=resolved_route_model,
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                    was_rotated=was_rotated,
                    tool_calling=request_tool_calling or is_tool_calling_response(body),
                    response_json=body,
                )
                return response.status_code, body, latency_ms

            await log_usage(
                session,
                app_token_id=app_token.id,
                provider_key_id=provider_key.id,
                protocol_in=protocol_in,
                protocol_out=protocol_out,
                route_kind=route_kind,
                queue_name=queue_name,
                model_requested=requested_model,
                provider_used=provider,
                resolved_model=resolved_route_model,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                status_code=response.status_code,
                was_rotated=was_rotated,
                tool_calling=request_tool_calling or is_tool_calling_response(body),
                response_json=body,
                error_message=failure_message[:500] if failure_message else None,
            )
            await mark_provider_key_model_soft_failure(session, provider_key, resolved_model_name)
            if attempt_index + 1 < len(provider_keys):
                was_rotated = True
                continue
            break

    return last_status_code, last_body, (time.perf_counter() - start_time) * 1000.0


async def proxy_chat_completion(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    *,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
) -> tuple[int, dict[str, object] | list[object] | str]:
    settings = get_settings()
    route_kind = "queue" if is_queue_route(payload.model) else "provider"
    queue_name = parse_queue_name(payload.model) if route_kind == "queue" else None
    try:
        routes = await resolve_model_routes(session, payload.model)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_409_CONFLICT, status.HTTP_502_BAD_GATEWAY}:
            error_text = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
            if route_kind == "queue" and queue_name:
                await _best_effort_send_alert(
                    format_queue_exhausted_alert(
                        app_token_name=app_token.name,
                        queue_name=queue_name,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    )
                )
            else:
                provider = payload.model.split("/", 1)[0] if "/" in payload.model else "unknown"
                await _best_effort_send_alert(
                    format_provider_pool_exhausted_alert(
                        app_token_name=app_token.name,
                        provider=provider,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    )
                )
        raise
    last_status_code = status.HTTP_502_BAD_GATEWAY
    last_body: dict[str, object] | list[object] | str = {"detail": "Proxy request failed"}

    for attempt_index, route in enumerate(routes):
        route_payload = payload.model_copy(update={"model": route.route})
        try:
            status_code, body, latency_ms = await _proxy_chat_completion_for_route(
                session,
                app_token,
                route_payload,
                route.route,
                requested_model=payload.model,
                queue_name=route.queue_name,
                protocol_in=protocol_in,
                protocol_out=protocol_out,
            )
        except HTTPException as exc:
            status_code = exc.status_code
            detail = exc.detail if isinstance(exc.detail, (dict, list)) else {"detail": str(exc.detail)}
            body = detail
            latency_ms = 0.0

        if route.queue_name and route.candidate_id is not None:
            candidate = await session.get(ModelQueueCandidate, route.candidate_id)
            if candidate is not None:
                if 200 <= status_code < 300:
                    await update_queue_candidate_on_success(session, candidate, latency_ms)
                else:
                    await update_queue_candidate_on_failure(session, candidate, status_code, latency_ms)

        if 200 <= status_code < 300:
            return status_code, body

        last_status_code = status_code
        last_body = body

        if attempt_index + 1 < len(routes):
            continue

    if last_status_code >= 400:
        await _send_resolution_alert(
            app_token=app_token,
            requested_model=payload.model,
            route_kind=route_kind,
            queue_name=queue_name,
            protocol_in=protocol_in,
            protocol_out=protocol_out,
            status_code=last_status_code,
            attempts=len(routes),
            rotated=len(routes) > 1,
            tool_calling=is_tool_calling_payload(payload.model_dump(exclude_none=True, exclude={"model"})),
            final_route=routes[-1].route if routes else None,
            error=_extract_error_text(last_body),
        )

    return last_status_code, last_body


async def proxy_chat_completion_stream(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    *,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
) -> StreamingResponse:
    settings = get_settings()
    route_kind = "queue" if is_queue_route(payload.model) else "provider"
    queue_name = parse_queue_name(payload.model) if route_kind == "queue" else None
    try:
        routes = await resolve_model_routes(session, payload.model)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_409_CONFLICT, status.HTTP_502_BAD_GATEWAY}:
            error_text = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
            if route_kind == "queue" and queue_name:
                await _best_effort_send_alert(
                    format_queue_exhausted_alert(
                        app_token_name=app_token.name,
                        queue_name=queue_name,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    )
                )
            else:
                provider = payload.model.split("/", 1)[0] if "/" in payload.model else "unknown"
                await _best_effort_send_alert(
                    format_provider_pool_exhausted_alert(
                        app_token_name=app_token.name,
                        provider=provider,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    )
                )
        raise

    last_error: str | dict[str, object] | list[object] | None = None
    last_status_code = status.HTTP_502_BAD_GATEWAY
    for attempt_index, route in enumerate(routes):
        route_payload = payload.model_copy(update={"model": route.route})
        try:
            return await _proxy_chat_completion_stream_for_route(
                session,
                app_token,
                route_payload,
                route.route,
                requested_model=payload.model,
                queue_name=route.queue_name,
                protocol_in=protocol_in,
                protocol_out=protocol_out,
            )
        except HTTPException as exc:
            last_status_code = exc.status_code
            last_error = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
            if attempt_index + 1 < len(routes):
                continue
            break

    if last_status_code >= 400:
        await _send_resolution_alert(
            app_token=app_token,
            requested_model=payload.model,
            route_kind=route_kind,
            queue_name=queue_name,
            protocol_in=protocol_in,
            protocol_out=protocol_out,
            status_code=last_status_code,
            attempts=len(routes),
            rotated=len(routes) > 1,
            tool_calling=is_tool_calling_payload(payload.model_dump(exclude_none=True, exclude={"model"})),
            final_route=routes[-1].route if routes else None,
            error=last_error,
        )

    raise HTTPException(status_code=last_status_code, detail=last_error or "Proxy request failed")


async def _proxy_chat_completion_stream_for_route(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    route_model: str,
    *,
    requested_model: str | None = None,
    queue_name: str | None = None,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
) -> StreamingResponse:
    requested_model = requested_model or route_model
    provider, model_name = parse_model_identifier(route_model)
    try:
        driver = get_provider_driver(provider)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider '{provider}'") from exc
    resolve_model_name = getattr(driver, "resolve_model_name", None)
    resolved_model_name = resolve_model_name(model_name) if callable(resolve_model_name) else model_name
    resolved_route_model = f"{provider}/{resolved_model_name}"

    settings = get_settings()
    provider_keys = await get_eligible_provider_keys(session, provider, resolved_model_name)
    if not provider_keys:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await build_provider_pool_exhausted_message(session, provider, resolved_model_name),
        )

    request_payload = payload.model_dump(exclude_none=True, exclude={"model"})
    request_payload.update(payload.model_extra or {})
    route_kind = "queue" if queue_name else "provider"
    request_tool_calling = is_tool_calling_payload(request_payload)

    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    timeout = httpx.Timeout(settings.proxy_timeout_seconds)
    start_time = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt_index, provider_key in enumerate(provider_keys):
            request = client.build_request(
                "POST",
                driver.build_url(resolved_model_name),
                headers=driver.build_headers(decrypt_text(provider_key.encrypted_token)),
                json=driver.build_payload(request_payload, resolved_model_name),
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                failure_message = str(exc) or "Provider request failed"
                await mark_provider_key_model_soft_failure(session, provider_key, resolved_model_name)
                await log_usage(
                    session,
                    app_token_id=app_token.id,
                    provider_key_id=provider_key.id,
                    protocol_in=protocol_in,
                    protocol_out=protocol_out,
                    route_kind=route_kind,
                    queue_name=queue_name,
                    model_requested=requested_model,
                    provider_used=provider,
                    resolved_model=resolved_route_model,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    was_rotated=attempt_index > 0,
                    tool_calling=request_tool_calling,
                    response_json={"detail": failure_message},
                    error_message=failure_message[:500],
                )
                if attempt_index + 1 < len(provider_keys):
                    continue
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=failure_message) from exc

            if response.status_code != status.HTTP_200_OK:
                body_text = await response.aread()
                await response.aclose()
                failure_message = body_text.decode("utf-8", errors="ignore") or "Upstream provider error"
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    failure_message = failure_message or format_rate_limit_message(provider)
                    retry_after_seconds = parse_retry_after_seconds(response.headers) or settings.key_cooldown_seconds
                    await mark_provider_key_model_failure(session, provider_key, resolved_model_name, retry_after_seconds)
                elif response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
                    await mark_provider_key_auth_failed(session, provider_key, response.status_code, failure_message)
                else:
                    await mark_provider_key_model_soft_failure(session, provider_key, resolved_model_name)

                await log_usage(
                    session,
                    app_token_id=app_token.id,
                    provider_key_id=provider_key.id,
                    protocol_in=protocol_in,
                    protocol_out=protocol_out,
                    route_kind=route_kind,
                    queue_name=queue_name,
                    model_requested=requested_model,
                    provider_used=provider,
                    resolved_model=resolved_route_model,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    status_code=response.status_code,
                    was_rotated=attempt_index > 0,
                    tool_calling=request_tool_calling,
                    response_json={"detail": failure_message},
                    error_message=failure_message[:500],
                )
                if attempt_index + 1 < len(provider_keys):
                    continue
                raise HTTPException(status_code=response.status_code, detail=failure_message)

            await mark_provider_key_model_success(session, provider_key, resolved_model_name)
            await mark_provider_key_success(session, provider_key)

            async def stream_generator() -> object:
                buffer = ""
                try:
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            block, buffer = buffer.split("\n\n", 1)
                            if not block.strip():
                                continue
                            data_lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
                            if not data_lines:
                                yield f"{block}\n\n"
                                continue

                            data_text = "\n".join(data_lines).strip()
                            if data_text == "[DONE]":
                                yield "data: [DONE]\n\n"
                                continue

                            try:
                                parsed_event = json.loads(data_text)
                            except json.JSONDecodeError:
                                yield f"data: {data_text}\n\n"
                                continue

                            normalized_event = driver.normalize_stream_event(parsed_event, resolved_model_name)
                            if isinstance(normalized_event, (dict, list)):
                                yield f"data: {json.dumps(normalized_event, ensure_ascii=False)}\n\n"
                            elif isinstance(normalized_event, str):
                                yield f"data: {normalized_event}\n\n"
                            else:
                                yield f"data: {data_text}\n\n"

                    if buffer.strip():
                        leftover = buffer.strip()
                        if leftover == "[DONE]":
                            yield "data: [DONE]\n\n"
                        else:
                            yield f"data: {leftover}\n\n"
                finally:
                    await response.aclose()
                    await log_usage(
                        session,
                        app_token_id=app_token.id,
                        provider_key_id=provider_key.id,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        route_kind=route_kind,
                        queue_name=queue_name,
                        model_requested=requested_model,
                        provider_used=provider,
                        resolved_model=resolved_route_model,
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        status_code=response.status_code,
                        was_rotated=attempt_index > 0,
                        tool_calling=request_tool_calling,
                        response_json=None,
                    )

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers=stream_headers,
            )

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Proxy request failed")
