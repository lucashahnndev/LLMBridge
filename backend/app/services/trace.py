from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.app.core.config import Settings
from backend.app.core.logging import request_body_ctx, request_id_ctx


logger = logging.getLogger(__name__)

SENSITIVE_KEY_MARKERS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "encrypted_token",
    "auth_token",
    "bearer",
}

SENSITIVE_VALUE_PREFIXES = (
    "bearer ",
    "sk-",
    "lk-key-",
    "xoxb-",
    "xoxp-",
    "ya29.",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return _jsonable(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _looks_sensitive_string(value: str) -> bool:
    lowered = value.lower().strip()
    return any(lowered.startswith(prefix) for prefix in SENSITIVE_VALUE_PREFIXES)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and _looks_sensitive_string(value):
        return "[redacted]"
    return value


def _deep_merge(target: dict[str, Any], path: list[str], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        node = cursor.get(part)
        if not isinstance(node, dict):
            node = {}
            cursor[part] = node
        cursor = node
    cursor[path[-1]] = value


@dataclass
class ProxyTraceRecorder:
    enabled: bool
    directory: Path
    request_id: str
    redact: bool = True
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProxyTraceRecorder":
        request_id = request_id_ctx.get("-")
        if not request_id or request_id == "-":
            request_id = uuid4().hex[:12]
        return cls(
            enabled=bool(settings.trace_proxy_enabled),
            directory=Path(settings.trace_proxy_dir or "traces"),
            request_id=request_id,
            redact=bool(settings.trace_proxy_redact),
        )

    def _ensure_enabled(self) -> bool:
        return self.enabled

    def _store(self, path: list[str], value: Any) -> None:
        if not self._ensure_enabled():
            return
        normalized = _jsonable(value)
        if self.redact:
            normalized = _redact(normalized)
        _deep_merge(self.payload, path, normalized)

    def start(self, *, protocol_in: str, request_payload: Any, app_token_name: str | None = None) -> None:
        self._store(["trace", "request_id"], self.request_id)
        self._store(["trace", "started_at"], _now_iso())
        self._store(["client", "protocol_in"], protocol_in)
        if app_token_name:
            self._store(["client", "app_token_name"], app_token_name)
        raw_body = request_body_ctx.get(None)
        if isinstance(raw_body, str) and raw_body.strip():
            try:
                parsed_raw_body = json.loads(raw_body)
            except json.JSONDecodeError:
                parsed_raw_body = raw_body
            self._store(["client", "raw_body"], parsed_raw_body)
        self._store(["client", "payload"], request_payload)

    def record_route(
        self,
        *,
        route_kind: str,
        requested_model: str,
        resolved_routes: list[str] | None = None,
        queue_name: str | None = None,
        gateway_providers: list[str] | None = None,
        downstream_targets: list[str] | None = None,
    ) -> None:
        self._store(["route", "kind"], route_kind)
        self._store(["route", "requested_model"], requested_model)
        if queue_name:
            self._store(["route", "queue_name"], queue_name)
        if resolved_routes is not None:
            self._store(["route", "resolved_routes"], resolved_routes)
        if gateway_providers is not None:
            self._store(["route", "gateway_providers"], gateway_providers)
        if downstream_targets is not None:
            self._store(["route", "downstream_targets"], downstream_targets)

    def record_resolution(self, *, route: Any, candidate_index: int | None = None) -> None:
        self._store(["route", "selected"], route)
        if isinstance(route, dict):
            provider = route.get("provider")
            model_name = route.get("model_name")
            if isinstance(provider, str) and provider.strip():
                self._store(["route", "selected_gateway_provider"], provider)
            if isinstance(model_name, str) and model_name.strip():
                self._store(["route", "selected_downstream_target"], model_name)
            route_text = route.get("route")
            if isinstance(route_text, str) and route_text.strip():
                self._store(["route", "selected_route"], route_text)
        if candidate_index is not None:
            self._store(["route", "candidate_index"], candidate_index)

    def record_canonical_request(self, canonical_request: Any) -> None:
        self._store(["canonical", "request"], canonical_request)

    def record_provider_attempt(
        self,
        *,
        attempt_index: int,
        provider_key_id: int | None,
        provider_key_name: str | None,
        provider: str,
        model: str,
        payload: Any,
    ) -> None:
        attempt: dict[str, Any] = {
            "attempt_index": attempt_index,
            "provider": provider,
            "model": model,
            "provider_key_id": provider_key_id,
            "provider_key_name": provider_key_name,
            "payload": _redact(_jsonable(payload)) if self.redact else _jsonable(payload),
        }
        attempts = self.payload.setdefault("provider", {}).setdefault("attempts", [])
        if isinstance(attempts, list):
            attempts.append(attempt)

    def record_provider_response(
        self,
        *,
        status_code: int,
        body: Any,
        latency_ms: float,
        attempt_index: int | None = None,
    ) -> None:
        response_payload = {
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "body": _redact(_jsonable(body)) if self.redact else _jsonable(body),
        }
        if attempt_index is not None:
            response_payload["attempt_index"] = attempt_index
        responses = self.payload.setdefault("provider", {}).setdefault("responses", [])
        if isinstance(responses, list):
            responses.append(response_payload)

    def record_canonical_response(self, canonical_response: Any) -> None:
        self._store(["canonical", "response"], canonical_response)

    def record_final_response(self, *, status_code: int, body: Any, latency_ms: float | None = None) -> None:
        self._store(["result", "status_code"], status_code)
        if latency_ms is not None:
            self._store(["result", "latency_ms"], round(latency_ms, 2))
        self._store(["result", "body"], body)

    def record_error(self, *, message: str, stage: str | None = None, status_code: int | None = None) -> None:
        entry: dict[str, Any] = {"message": message}
        if stage:
            entry["stage"] = stage
        if status_code is not None:
            entry["status_code"] = status_code
        errors = self.payload.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(entry)

    def finish(self) -> None:
        if not self._ensure_enabled():
            return
        self._store(["trace", "finished_at"], _now_iso())

    def write(self) -> None:
        if not self._ensure_enabled():
            return
        self.finish()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{self.request_id}.json"
            payload = self.payload if self.payload else {"trace": {"request_id": self.request_id}}
            if self.redact:
                payload = _redact(_jsonable(payload))
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("failed to write proxy trace")
