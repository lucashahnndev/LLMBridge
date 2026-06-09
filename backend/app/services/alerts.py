from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from backend.app.core.config import get_settings


async def send_telegram_alert(message: str) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    return True


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _coerce_error_message(error: str | dict[str, object] | list[object] | None) -> str:
    if error is None:
        return "Proxy request failed"
    if isinstance(error, str):
        text = error.strip()
        return text or "Proxy request failed"
    if isinstance(error, list):
        return json.dumps(error, ensure_ascii=False)
    detail = error.get("detail") if isinstance(error, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    nested_error = error.get("error") if isinstance(error, dict) else None
    if isinstance(nested_error, dict):
        message = nested_error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return json.dumps(error, ensure_ascii=False)


def format_proxy_failure_alert(
    *,
    app_token_name: str,
    requested_model: str,
    final_route: str | None,
    route_kind: str,
    queue_name: str | None,
    protocol_in: str,
    protocol_out: str,
    status_code: int,
    attempts: int,
    tool_calling: bool,
    rotated: bool,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    lines = [
        "[LLMBridge] Proxy failure",
        f"Time: {_now_utc()}",
        f"App token: {app_token_name}",
        f"Requested model: {requested_model}",
        f"Final route: {final_route or 'n/a'}",
        f"Route kind: {route_kind}",
    ]
    if queue_name:
        lines.append(f"Queue: {queue_name}")
    lines.extend(
        [
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Status: {status_code}",
            f"Attempts: {attempts}",
            f"Rotated: {'yes' if rotated else 'no'}",
            f"Tool calling: {'yes' if tool_calling else 'no'}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )
    return "\n".join(lines)


def format_queue_exhausted_alert(
    *,
    app_token_name: str,
    queue_name: str,
    requested_model: str,
    protocol_in: str,
    protocol_out: str,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    return "\n".join(
        [
            "[LLMBridge] Queue exhausted",
            f"Time: {_now_utc()}",
            f"App token: {app_token_name}",
            f"Queue: {queue_name}",
            f"Requested model: {requested_model}",
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )


def format_provider_pool_exhausted_alert(
    *,
    app_token_name: str,
    provider: str,
    requested_model: str,
    protocol_in: str,
    protocol_out: str,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    return "\n".join(
        [
            "[LLMBridge] Provider pool exhausted",
            f"Time: {_now_utc()}",
            f"App token: {app_token_name}",
            f"Provider: {provider}",
            f"Requested model: {requested_model}",
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )
