from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
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
from backend.app.services.canonical import (
    canonical_request_to_chat_completion,
    chat_completion_body_to_canonical_response,
    openai_request_to_canonical,
)
from backend.app.services.classifier import RouteClassificationEvent, dispatch_route_classification_event
from backend.app.services.availability import list_balanced_provider_keys_for_route, summarize_provider_route_availability
from backend.app.services.alerts import (
    AlertChannel,
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
    update_queue_candidate_on_failure,
    update_queue_candidate_on_success,
)
from backend.app.services.trace import ProxyTraceRecorder
from backend.app.services.records import ensure_utc_datetime
from backend.app.services.retry_parser import parse_retry_after_seconds
from backend.app.services.route_materializer import ensure_materialized_route_snapshot


logger = logging.getLogger(__name__)

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


async def get_eligible_provider_keys(
    session: AsyncSession,
    provider: str,
    model_name: str,
) -> list[ProviderKey]:
    return await list_balanced_provider_keys_for_route(
        session,
        provider=provider,
        model_name=model_name,
    )


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


def chat_completion_body_to_stream_events(body: dict[str, object]) -> list[dict[str, object]]:
    choices = body.get("choices")
    if not isinstance(choices, list):
        return []

    events: list[dict[str, object]] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue

        delta: dict[str, object] = {"role": message.get("role") or "assistant"}
        content = message.get("content")
        if content is not None:
            delta["content"] = content
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            delta["tool_calls"] = tool_calls

        events.append(
            {
                "id": body.get("id") or "chatcmpl-stream-bridge",
                "object": "chat.completion.chunk",
                "created": body.get("created"),
                "model": body.get("model"),
                "choices": [
                    {
                        "index": choice.get("index") or 0,
                        "delta": delta,
                        "finish_reason": choice.get("finish_reason"),
                    }
                ],
            }
        )
    return events


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


async def _best_effort_send_alert(session: AsyncSession, message: str, *, channel: AlertChannel | None = None) -> None:
    try:
        await send_telegram_alert(message, session=session, channel=channel)
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
    session: AsyncSession,
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
    await _best_effort_send_alert(session, alert_message, channel=AlertChannel.PROXY_FAILURE)


async def mark_provider_key_success(session: AsyncSession, provider_key: ProviderKey) -> None:
    if provider_key.status != KeyStatus.ACTIVE or provider_key.failure_count != 0 or provider_key.blocked_until is not None:
        provider_key.status = KeyStatus.ACTIVE
        provider_key.blocked_until = None
        provider_key.failure_count = 0
        await session.commit()


async def mirror_provider_key_model_cooldown_legacy(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
    *,
    blocked_until: datetime | None = None,
    failure_count_delta: int = 0,
    clear: bool = False,
) -> None:
    # Deprecated compatibility mirror.
    # Operational availability is stored in provider_key_route_states.
    settings = get_settings()
    if not settings.legacy_cooldown_mirror_enabled:
        return

    try:
        existing = await session.execute(
            select(ProviderKeyModelCooldown).where(
                ProviderKeyModelCooldown.provider_key_id == provider_key.id,
                ProviderKeyModelCooldown.model_name == model_name,
            )
        )
        cooldown = existing.scalar_one_or_none()
        if clear:
            if cooldown is None:
                return
            if cooldown.failure_count <= 1:
                await session.delete(cooldown)
            else:
                cooldown.failure_count = cooldown.failure_count - 1
            await session.commit()
            return

        if failure_count_delta <= 0 and blocked_until is None:
            return

        next_failure_count = max(1, failure_count_delta if cooldown is None else cooldown.failure_count + max(1, failure_count_delta))
        next_blocked_until = blocked_until
        if cooldown is None:
            cooldown = ProviderKeyModelCooldown(
                provider_key_id=provider_key.id,
                model_name=model_name,
                blocked_until=next_blocked_until,
                failure_count=next_failure_count,
            )
            session.add(cooldown)
        else:
            if next_blocked_until is not None:
                current_blocked_until = ensure_utc_datetime(cooldown.blocked_until)
                cooldown.blocked_until = max(current_blocked_until or next_blocked_until, next_blocked_until)
            cooldown.failure_count = next_failure_count
        await session.commit()
    except Exception:
        logger.exception(
            "Legacy ProviderKeyModelCooldown mirror failed",
            extra={
                "provider_key_id": provider_key.id,
                "provider": provider_key.provider,
                "model_name": model_name,
            },
        )


async def mark_provider_key_model_failure(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
    retry_after_seconds: int | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    blocked_until = now + timedelta(seconds=max(1, retry_after_seconds)) if retry_after_seconds is not None else now
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=provider_key.provider,
            model_name=model_name,
            key_id=provider_key.id,
            success=False,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            latency_ms=0.0,
            started_at=now,
            finished_at=now,
            retry_hint_seconds=retry_after_seconds,
            error_message="rate limit",
        ),
        swallow_errors=True,
    )
    await mirror_provider_key_model_cooldown_legacy(
        session,
        provider_key,
        model_name,
        blocked_until=blocked_until,
        failure_count_delta=1,
    )


async def mark_provider_key_model_success(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
) -> None:
    now = datetime.now(timezone.utc)
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=provider_key.provider,
            model_name=model_name,
            key_id=provider_key.id,
            success=True,
            status_code=200,
            latency_ms=0.0,
            started_at=now,
            finished_at=now,
        ),
        swallow_errors=True,
    )
    await mirror_provider_key_model_cooldown_legacy(
        session,
        provider_key,
        model_name,
        clear=True,
    )


async def mark_provider_key_model_soft_failure(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
    cooldown_seconds: int | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    blocked_until = now + timedelta(seconds=max(1, cooldown_seconds)) if cooldown_seconds is not None else now
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=provider_key.provider,
            model_name=model_name,
            key_id=provider_key.id,
            success=False,
            status_code=status.HTTP_502_BAD_GATEWAY,
            latency_ms=0.0,
            started_at=now,
            finished_at=now,
            retry_hint_seconds=cooldown_seconds,
            error_message="provider request failed",
        ),
        swallow_errors=True,
    )
    await mirror_provider_key_model_cooldown_legacy(
        session,
        provider_key,
        model_name,
        blocked_until=blocked_until,
        failure_count_delta=1,
    )


async def mark_provider_key_auth_failed(
    session: AsyncSession,
    provider_key: ProviderKey,
    model_name: str,
    status_code: int,
    error_text: str,
) -> None:
    now = datetime.now(timezone.utc)
    await dispatch_route_classification_event(
        session,
        RouteClassificationEvent(
            provider=provider_key.provider,
            model_name=model_name,
            key_id=provider_key.id,
            success=False,
            status_code=status_code,
            latency_ms=0.0,
            started_at=now,
            finished_at=now,
            error_message=error_text,
        ),
        swallow_errors=True,
    )


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
    availability = await summarize_provider_route_availability(
        session,
        provider=provider,
        model_name=model_name,
    )
    summary = availability.summary
    total = (
        int(summary["eligible_count"])
        + int(summary["cooldown_count"])
        + int(summary["disabled_count"])
        + int(summary["blocked_count"])
    )
    invalid = int(summary["disabled_count"])
    model_cooldown_count = int(summary["cooldown_count"])
    next_retry_at = summary["smallest_cooldown_until"]
    valid = total - invalid - int(summary["blocked_count"])
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
        active=max(0, int(summary["eligible_count"])),
        cooldown=model_cooldown_count,
        invalid=invalid,
        next_retry_at=next_retry_at,
    )


def should_rotate_to_next_key(status_code: int, error_text: str | None = None) -> bool:
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return True
    if status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }:
        return True
    if error_text:
        lowered = error_text.lower()
        return any(
            keyword in lowered
            for keyword in (
                "rate limit",
                "ratelimit",
                "quota",
                "over quota",
                "quota exceeded",
                "too many requests",
                "resource exhausted",
                "exhausted",
            )
        )
    return False


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


def classify_model_failure_cooldown_seconds(
    *,
    status_code: int,
    failure_message: str | None,
    retry_after_seconds: int | None,
    settings: object,
) -> int | None:
    lowered = failure_message.lower() if failure_message else ""
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return retry_after_seconds or getattr(settings, "key_cooldown_seconds", 300)
    if status_code == status.HTTP_404_NOT_FOUND or any(
        keyword in lowered
        for keyword in ("not found", "not supported", "unsupported", "unknown model", "model unavailable")
    ):
        return getattr(settings, "provider_model_not_found_cooldown_seconds", 3600)
    if status_code >= 500:
        return getattr(settings, "provider_transient_failure_cooldown_seconds", 30)
    return getattr(settings, "provider_transient_failure_cooldown_seconds", 30)


async def _proxy_chat_completion_for_route(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    route_model: str,
    client: httpx.AsyncClient,
    *,
    requested_model: str | None = None,
    queue_name: str | None = None,
    provider_key_id: int | None = None,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
    trace: ProxyTraceRecorder | None = None,
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
    if provider_key_id is not None:
        selected_provider_key = await session.get(ProviderKey, provider_key_id)
        provider_keys = [selected_provider_key] if selected_provider_key is not None else []
    else:
        provider_keys = await get_eligible_provider_keys(session, provider, resolved_model_name)
    if not provider_keys:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await build_provider_pool_exhausted_message(session, provider, resolved_model_name),
        )

    route_kind = "queue" if queue_name else "provider"
    canonical_request = openai_request_to_canonical(
        payload,
        protocol_in=protocol_in,
        route_kind=route_kind,
        queue_name=queue_name,
        provider=provider,
        model_name=resolved_model_name,
        requested_model=requested_model,
    )
    if trace is not None:
        trace.record_canonical_request(canonical_request)
    request_payload = canonical_request_to_chat_completion(
        canonical_request,
        model_override=resolved_route_model,
    ).model_dump(exclude_none=True, exclude={"model"})
    if payload.user is not None:
        request_payload["user"] = payload.user
    request_tool_calling = is_tool_calling_payload(request_payload)

    start_time = time.perf_counter()
    last_status_code = 502
    last_body: dict[str, object] | list[object] | str = {"detail": "Proxy request failed"}
    used_key: ProviderKey | None = None
    was_rotated = False

    use_google_native = provider == "google" and hasattr(driver, "build_native_payload")
    provider_payload = request_payload
    if use_google_native:
        provider_payload = driver.build_native_payload(canonical_request, resolved_model_name)
    for attempt_index, provider_key in enumerate(provider_keys):
        used_key = provider_key
        if trace is not None:
            trace.record_provider_attempt(
                attempt_index=attempt_index,
                provider_key_id=provider_key.id,
                provider_key_name=provider_key.name,
                provider=provider,
                model=resolved_route_model,
                payload=provider_payload,
            )
        try:
            provider_token = decrypt_text(provider_key.encrypted_token)
            if use_google_native:
                response = await driver.send_native_chat_completion(
                    client=client,
                    provider_token=provider_token,
                    canonical=canonical_request,
                    model_name=resolved_model_name,
                )
            else:
                response = await driver.send_chat_completion(
                    client=client,
                    provider_token=provider_token,
                    normalized_payload=request_payload,
                    model_name=resolved_model_name,
                )
        except httpx.HTTPError as exc:
            failure_message = str(exc) or "Provider request failed"
            failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
                status_code=status.HTTP_502_BAD_GATEWAY,
                failure_message=failure_message,
                retry_after_seconds=None,
                settings=settings,
            )
            if trace is not None:
                trace.record_provider_response(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    body={"detail": failure_message},
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    attempt_index=attempt_index,
                )
            await mark_provider_key_model_soft_failure(
                session,
                provider_key,
                resolved_model_name,
                cooldown_seconds=failure_cooldown_seconds,
            )
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
        if trace is not None:
            trace.record_provider_response(
                status_code=response.status_code,
                body=body,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                attempt_index=attempt_index,
            )

        failure_message = extract_failure_message(
            body,
            "Provider request failed",
        )
        retry_after_seconds = parse_retry_after_seconds(response.headers, body=body, provider=provider)
        failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
            status_code=response.status_code,
            failure_message=failure_message,
            retry_after_seconds=retry_after_seconds,
            settings=settings,
        )

        if 200 <= response.status_code < 300:
            await mark_provider_key_model_success(session, provider_key, resolved_model_name)
            await mark_provider_key_success(session, provider_key)
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            body = driver.normalize_response_body(body, resolved_model_name)
            canonical_response = chat_completion_body_to_canonical_response(
                body if isinstance(body, dict) else {"detail": "Non-JSON response"},
                model_name=resolved_route_model,
                protocol_out=protocol_out,
            )
            if trace is not None:
                trace.record_canonical_response(canonical_response)
                trace.record_final_response(status_code=response.status_code, body=body, latency_ms=latency_ms)
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

        if should_rotate_to_next_key(response.status_code, failure_message):
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                retry_after_seconds = retry_after_seconds or settings.key_cooldown_seconds
                await mark_provider_key_model_failure(session, provider_key, resolved_model_name, retry_after_seconds)
            elif response.status_code in {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            }:
                await mark_provider_key_auth_failed(session, provider_key, resolved_model_name, response.status_code, failure_message)
            else:
                await mark_provider_key_model_soft_failure(
                    session,
                    provider_key,
                    resolved_model_name,
                    cooldown_seconds=failure_cooldown_seconds,
                )
            if attempt_index + 1 < len(provider_keys):
                was_rotated = True
                continue
            break

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
        await mark_provider_key_model_soft_failure(
            session,
            provider_key,
            resolved_model_name,
            cooldown_seconds=failure_cooldown_seconds,
        )
        if attempt_index + 1 < len(provider_keys):
            was_rotated = True
            continue
        break

    return last_status_code, last_body, (time.perf_counter() - start_time) * 1000.0


async def proxy_chat_completion(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    client: httpx.AsyncClient | None = None,
    *,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
    trace: ProxyTraceRecorder | None = None,
) -> tuple[int, dict[str, object] | list[object] | str]:
    settings = get_settings()
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=settings.proxy_timeout_seconds)
    trace = trace or ProxyTraceRecorder.from_settings(settings)
    try:
        if trace.enabled:
            trace.start(protocol_in=protocol_in, request_payload=payload, app_token_name=app_token.name)
        route_kind = "queue" if is_queue_route(payload.model) else "provider"
        queue_name = parse_queue_name(payload.model) if route_kind == "queue" else None
        try:
            snapshot = await ensure_materialized_route_snapshot(session, payload.model)
            routes = snapshot.routes
        except HTTPException as exc:
            if trace.enabled:
                trace.record_error(
                    message=str(exc.detail) if exc.detail is not None else "Route resolution failed",
                    stage="route_resolution",
                    status_code=exc.status_code,
                )
            if exc.status_code in {
                status.HTTP_409_CONFLICT,
                status.HTTP_429_TOO_MANY_REQUESTS,
                status.HTTP_502_BAD_GATEWAY,
                status.HTTP_503_SERVICE_UNAVAILABLE,
            }:
                error_text = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
                if route_kind == "queue" and queue_name:
                    await _best_effort_send_alert(
                        session,
                        format_queue_exhausted_alert(
                            app_token_name=app_token.name,
                            queue_name=queue_name,
                            requested_model=payload.model,
                            protocol_in=protocol_in,
                            protocol_out=protocol_out,
                            error=error_text,
                        ),
                        channel=AlertChannel.QUEUE_EXHAUSTED,
                    )
                else:
                    provider = payload.model.split("/", 1)[0] if "/" in payload.model else "unknown"
                    await _best_effort_send_alert(
                        session,
                        format_provider_pool_exhausted_alert(
                            app_token_name=app_token.name,
                            provider=provider,
                            requested_model=payload.model,
                            protocol_in=protocol_in,
                            protocol_out=protocol_out,
                            error=error_text,
                        ),
                        channel=AlertChannel.PROVIDER_POOL_EXHAUSTED,
                    )
            if trace.enabled:
                trace.write()
            raise
        if trace.enabled:
            trace.record_route(
                route_kind=route_kind,
                requested_model=payload.model,
                resolved_routes=[route.route for route in routes],
                queue_name=queue_name,
            )
        last_status_code = status.HTTP_502_BAD_GATEWAY
        last_body: dict[str, object] | list[object] | str = {"detail": "Proxy request failed"}

        for attempt_index, route in enumerate(routes):
            route_payload = payload.model_copy(update={"model": route.route})
            if trace.enabled:
                trace.record_resolution(
                    route=asdict(route),
                    candidate_index=attempt_index,
                )
            try:
                status_code, body, latency_ms = await _proxy_chat_completion_for_route(
                    session,
                    app_token,
                    route_payload,
                    route.route,
                    client,
                    requested_model=payload.model,
                    queue_name=route.queue_name,
                    provider_key_id=route.provider_key_id,
                    protocol_in=protocol_in,
                    protocol_out=protocol_out,
                    trace=trace,
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
                        error_text = extract_failure_message(body, "Provider request failed")
                        await update_queue_candidate_on_failure(
                            session,
                            candidate,
                            status_code,
                            latency_ms,
                            error_message=error_text,
                        )

            if 200 <= status_code < 300:
                if trace.enabled:
                    trace.record_final_response(status_code=status_code, body=body)
                    trace.write()
                return status_code, body

            last_status_code = status_code
            last_body = body

            if attempt_index + 1 < len(routes):
                continue

        if last_status_code >= 400:
            await _send_resolution_alert(
                session,
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

        if trace.enabled:
            trace.record_final_response(status_code=last_status_code, body=last_body)
            trace.write()
        return last_status_code, last_body
    finally:
        if owns_client:
            await client.aclose()


async def proxy_chat_completion_stream(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    client: httpx.AsyncClient,
    *,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
    trace: ProxyTraceRecorder | None = None,
) -> StreamingResponse:
    settings = get_settings()
    trace = trace or ProxyTraceRecorder.from_settings(settings)
    if trace.enabled:
        trace.start(protocol_in=protocol_in, request_payload=payload, app_token_name=app_token.name)
    route_kind = "queue" if is_queue_route(payload.model) else "provider"
    queue_name = parse_queue_name(payload.model) if route_kind == "queue" else None
    try:
        snapshot = await ensure_materialized_route_snapshot(session, payload.model)
        routes = snapshot.routes
    except HTTPException as exc:
        if trace.enabled:
            trace.record_error(
                message=str(exc.detail) if exc.detail is not None else "Route resolution failed",
                stage="route_resolution",
                status_code=exc.status_code,
            )
        if exc.status_code in {
            status.HTTP_409_CONFLICT,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_502_BAD_GATEWAY,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        }:
            error_text = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
            if route_kind == "queue" and queue_name:
                await _best_effort_send_alert(
                    session,
                    format_queue_exhausted_alert(
                        app_token_name=app_token.name,
                        queue_name=queue_name,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    ),
                    channel=AlertChannel.QUEUE_EXHAUSTED,
                )
            else:
                provider = payload.model.split("/", 1)[0] if "/" in payload.model else "unknown"
                await _best_effort_send_alert(
                    session,
                    format_provider_pool_exhausted_alert(
                        app_token_name=app_token.name,
                        provider=provider,
                        requested_model=payload.model,
                        protocol_in=protocol_in,
                        protocol_out=protocol_out,
                        error=error_text,
                    ),
                    channel=AlertChannel.PROVIDER_POOL_EXHAUSTED,
                )
        if trace.enabled:
            trace.write()
        raise

    if trace.enabled:
        trace.record_route(
            route_kind=route_kind,
            requested_model=payload.model,
            resolved_routes=[route.route for route in routes],
            queue_name=queue_name,
        )

    last_error: str | dict[str, object] | list[object] | None = None
    last_status_code = status.HTTP_502_BAD_GATEWAY
    for attempt_index, route in enumerate(routes):
        route_payload = payload.model_copy(update={"model": route.route})
        if trace.enabled:
            trace.record_resolution(
                route=asdict(route),
                candidate_index=attempt_index,
            )
        try:
            return await _proxy_chat_completion_stream_for_route(
                session,
                app_token,
                route_payload,
                route.route,
                client,
                requested_model=payload.model,
                queue_name=route.queue_name,
                provider_key_id=route.provider_key_id,
                protocol_in=protocol_in,
                protocol_out=protocol_out,
                trace=trace,
            )
        except HTTPException as exc:
            last_status_code = exc.status_code
            last_error = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
            if attempt_index + 1 < len(routes):
                continue
            break

    if last_status_code >= 400:
        await _send_resolution_alert(
            session,
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

    if trace.enabled:
        trace.record_final_response(status_code=last_status_code, body=last_error or {"detail": "Proxy request failed"})
        trace.write()
    raise HTTPException(status_code=last_status_code, detail=last_error or "Proxy request failed")


async def _proxy_chat_completion_stream_for_route(
    session: AsyncSession,
    app_token: AppToken,
    payload: ChatCompletionRequest,
    route_model: str,
    client: httpx.AsyncClient,
    *,
    requested_model: str | None = None,
    queue_name: str | None = None,
    provider_key_id: int | None = None,
    protocol_in: str = "openai",
    protocol_out: str = "openai",
    trace: ProxyTraceRecorder | None = None,
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
    if provider_key_id is not None:
        selected_provider_key = await session.get(ProviderKey, provider_key_id)
        provider_keys = [selected_provider_key] if selected_provider_key is not None else []
    else:
        provider_keys = await get_eligible_provider_keys(session, provider, resolved_model_name)
    if not provider_keys:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=await build_provider_pool_exhausted_message(session, provider, resolved_model_name),
        )

    route_kind = "queue" if queue_name else "provider"
    canonical_request = openai_request_to_canonical(
        payload,
        protocol_in=protocol_in,
        route_kind=route_kind,
        queue_name=queue_name,
        provider=provider,
        model_name=resolved_model_name,
        requested_model=requested_model,
    )
    if trace is not None and trace.enabled:
        trace.record_canonical_request(canonical_request)
    request_payload = canonical_request_to_chat_completion(
        canonical_request,
        model_override=resolved_route_model,
    ).model_dump(exclude_none=True, exclude={"model"})
    if payload.user is not None:
        request_payload["user"] = payload.user
    request_tool_calling = is_tool_calling_payload(request_payload)

    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    start_time = time.perf_counter()
    use_google_native = provider == "google" and hasattr(driver, "build_native_payload")
    provider_payload = request_payload
    if use_google_native:
        provider_payload = driver.build_native_payload(canonical_request, resolved_model_name)

    for attempt_index, provider_key in enumerate(provider_keys):
        if trace is not None and trace.enabled:
            trace.record_provider_attempt(
                attempt_index=attempt_index,
                provider_key_id=provider_key.id,
                provider_key_name=provider_key.name,
                provider=provider,
                model=resolved_route_model,
                payload=provider_payload,
            )
        if use_google_native:
            try:
                response = await driver.send_native_chat_completion(
                    client=client,
                    provider_token=decrypt_text(provider_key.encrypted_token),
                    canonical=canonical_request,
                    model_name=resolved_model_name,
                )
            except httpx.HTTPError as exc:
                failure_message = str(exc) or "Provider request failed"
                failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    failure_message=failure_message,
                    retry_after_seconds=None,
                    settings=settings,
                )
                if trace is not None and trace.enabled:
                    trace.record_provider_response(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        body={"detail": failure_message},
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        attempt_index=attempt_index,
                    )
                await mark_provider_key_model_soft_failure(
                    session,
                    provider_key,
                    resolved_model_name,
                    cooldown_seconds=failure_cooldown_seconds,
                )
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

            body = coerce_response_body(response)
            failure_message = extract_failure_message(body, "Upstream provider error")
            retry_after_seconds = parse_retry_after_seconds(response.headers, body=body, provider=provider)
            failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
                status_code=response.status_code,
                failure_message=failure_message,
                retry_after_seconds=retry_after_seconds,
                settings=settings,
            )
            if response.status_code != status.HTTP_200_OK:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    retry_after_seconds = retry_after_seconds or settings.key_cooldown_seconds
                    await mark_provider_key_model_failure(session, provider_key, resolved_model_name, retry_after_seconds)
                elif response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
                    await mark_provider_key_auth_failed(session, provider_key, resolved_model_name, response.status_code, failure_message)
                else:
                    await mark_provider_key_model_soft_failure(
                        session,
                        provider_key,
                        resolved_model_name,
                        cooldown_seconds=failure_cooldown_seconds,
                    )

            if trace is not None and trace.enabled:
                trace.record_provider_response(
                    status_code=response.status_code,
                    body=body,
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    attempt_index=attempt_index,
                )

            if response.status_code != status.HTTP_200_OK:
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
                    tool_calling=request_tool_calling or is_tool_calling_response(body),
                    response_json=body,
                    error_message=failure_message[:500] if failure_message else None,
                )
                if attempt_index + 1 < len(provider_keys):
                    continue
                raise HTTPException(status_code=response.status_code, detail=failure_message)

            await mark_provider_key_model_success(session, provider_key, resolved_model_name)
            await mark_provider_key_success(session, provider_key)
            normalized_body = driver.normalize_response_body(body, resolved_model_name)
            if not isinstance(normalized_body, dict):
                normalized_body = {"detail": "Provider returned an unsupported streaming response shape"}
            stream_events = chat_completion_body_to_stream_events(normalized_body)

            async def google_native_stream_generator() -> object:
                normalized_chunks: list[str] = []
                try:
                    for event in stream_events:
                        event_text = json.dumps(event, ensure_ascii=False)
                        normalized_chunks.append(event_text)
                        yield f"data: {event_text}\n\n"
                    normalized_chunks.append("[DONE]")
                    yield "data: [DONE]\n\n"
                finally:
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
                        tool_calling=request_tool_calling or is_tool_calling_response(normalized_body),
                        response_json=normalized_body,
                    )
                    if trace is not None and trace.enabled:
                        trace.record_final_response(
                            status_code=response.status_code,
                            body={
                                "stream": True,
                                "provider_body": body,
                                "normalized_chunks": normalized_chunks,
                            },
                            latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        )
                        trace.write()

            return StreamingResponse(
                google_native_stream_generator(),
                media_type="text/event-stream",
                headers=stream_headers,
            )

        if not use_google_native:
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
                failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    failure_message=failure_message,
                    retry_after_seconds=None,
                    settings=settings,
                )
                if trace is not None and trace.enabled:
                    trace.record_provider_response(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        body={"detail": failure_message},
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        attempt_index=attempt_index,
                    )
                await mark_provider_key_model_soft_failure(
                    session,
                    provider_key,
                    resolved_model_name,
                    cooldown_seconds=failure_cooldown_seconds,
                )
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
                retry_after_seconds = parse_retry_after_seconds(response.headers, body=failure_message, provider=provider)
                if trace is not None and trace.enabled:
                    trace.record_provider_response(
                        status_code=response.status_code,
                        body={"detail": failure_message},
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        attempt_index=attempt_index,
                    )
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    failure_message = failure_message or format_rate_limit_message(provider)
                    retry_after_seconds = (
                        parse_retry_after_seconds(response.headers, body=failure_message, provider=provider)
                        or settings.key_cooldown_seconds
                    )
                    await mark_provider_key_model_failure(session, provider_key, resolved_model_name, retry_after_seconds)
                elif response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
                    await mark_provider_key_auth_failed(session, provider_key, resolved_model_name, response.status_code, failure_message)
                else:
                    failure_cooldown_seconds = classify_model_failure_cooldown_seconds(
                        status_code=response.status_code,
                        failure_message=failure_message,
                        retry_after_seconds=retry_after_seconds,
                        settings=settings,
                    )
                    await mark_provider_key_model_soft_failure(
                        session,
                        provider_key,
                        resolved_model_name,
                        cooldown_seconds=failure_cooldown_seconds,
                    )

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
                provider_chunks: list[str] = []
                normalized_chunks: list[str] = []
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
                            provider_chunks.append(data_text)
                            if data_text == "[DONE]":
                                normalized_chunks.append("[DONE]")
                                yield "data: [DONE]\n\n"
                                continue

                            try:
                                parsed_event = json.loads(data_text)
                            except json.JSONDecodeError:
                                normalized_chunks.append(data_text)
                                yield f"data: {data_text}\n\n"
                                continue

                            normalized_event = driver.normalize_stream_event(parsed_event, resolved_model_name)
                            if isinstance(normalized_event, (dict, list)):
                                normalized_text = json.dumps(normalized_event, ensure_ascii=False)
                                normalized_chunks.append(normalized_text)
                                yield f"data: {normalized_text}\n\n"
                            elif isinstance(normalized_event, str):
                                normalized_chunks.append(normalized_event)
                                yield f"data: {normalized_event}\n\n"
                            else:
                                normalized_chunks.append(data_text)
                                yield f"data: {data_text}\n\n"

                    if buffer.strip():
                        leftover = buffer.strip()
                        provider_chunks.append(leftover)
                        if leftover == "[DONE]":
                            normalized_chunks.append("[DONE]")
                            yield "data: [DONE]\n\n"
                        else:
                            normalized_chunks.append(leftover)
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
                    if trace is not None and trace.enabled:
                        trace.record_final_response(
                            status_code=response.status_code,
                            body={
                                "stream": True,
                                "provider_chunks": provider_chunks,
                                "normalized_chunks": normalized_chunks,
                            },
                            latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        )
                        trace.write()

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers=stream_headers,
            )

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Proxy request failed")
