from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
request_method_ctx: ContextVar[str] = ContextVar("request_method", default="-")
request_path_ctx: ContextVar[str] = ContextVar("request_path", default="-")
request_client_ctx: ContextVar[str] = ContextVar("request_client", default="-")
request_body_ctx: ContextVar[str | None] = ContextVar("request_body", default=None)

SENSITIVE_KEYS = {"authorization", "token", "secret", "password", "api_key", "apikey", "access_token", "refresh_token"}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        record.request_method = request_method_ctx.get("-")
        record.request_path = request_path_ctx.get("-")
        record.request_client = request_client_ctx.get("-")
        return True


def set_request_context(*, request_id: str, method: str, path: str, client: str = "-") -> None:
    request_id_ctx.set(request_id)
    request_method_ctx.set(method)
    request_path_ctx.set(path)
    request_client_ctx.set(client)


def clear_request_context() -> None:
    request_id_ctx.set("-")
    request_method_ctx.set("-")
    request_path_ctx.set("-")
    request_client_ctx.set("-")
    request_body_ctx.set(None)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(secret_key in lowered for secret_key in SENSITIVE_KEYS):
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "...[truncated]"
    return value


def sanitize_text(text: str) -> str:
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text
    sanitized = _sanitize_value(parsed)
    return json.dumps(sanitized, ensure_ascii=False, indent=2)


def setup_logging(settings: Settings) -> None:
    level = str(settings.log_level or "INFO").upper()
    logging.captureWarnings(True)

    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
            "formatter": "standard",
            "filters": ["request_context"],
        }
    }
    logger_handlers = ["console"]

    if settings.log_file_enabled:
        log_file = Path(settings.log_file_path or "logs/backend.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": level,
            "formatter": "standard",
            "filters": ["request_context"],
            "filename": str(log_file),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }
        logger_handlers.append("file")

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": RequestContextFilter,
            },
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | req=%(request_id)s | %(message)s",
            },
            "access": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | req=%(request_id)s | %(request_method)s %(request_path)s | %(message)s",
            },
        },
        "handlers": handlers,
        "loggers": {
            "uvicorn": {
                "level": level,
                "handlers": logger_handlers,
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
                "handlers": logger_handlers,
                "propagate": False,
            },
            "uvicorn.access": {
                "level": level,
                "handlers": logger_handlers,
                "propagate": False,
            },
            "backend": {
                "level": level,
                "handlers": logger_handlers,
                "propagate": False,
            },
        },
        "root": {
            "level": level,
            "handlers": logger_handlers,
        },
    }

    logging.config.dictConfig(config)


def summarize_debug_payload(payload: Any) -> str:
    if payload is None:
        return "null"
    if isinstance(payload, (dict, list)):
        return json.dumps(_sanitize_value(payload), ensure_ascii=False, indent=2)
    if isinstance(payload, bytes):
        try:
            return summarize_debug_payload(payload.decode("utf-8", errors="replace"))
        except Exception:
            return "[binary payload]"
    if isinstance(payload, str):
        return sanitize_text(payload)
    return str(payload)
