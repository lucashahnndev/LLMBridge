from __future__ import annotations

from backend.app.core.config import ENV_FILE, get_settings
from backend.app.schemas.runtime import RuntimeConfigResponse


def _parse_env_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _serialize_env_lines(values: dict[str, str]) -> str:
    ordered_keys = list(values.keys())
    lines = [f"{key}={values[key]}" for key in ordered_keys]
    return "\n".join(lines) + "\n"


def read_runtime_config() -> RuntimeConfigResponse:
    settings = get_settings()
    return RuntimeConfigResponse(
        host=settings.host,
        port=settings.port,
        api_base_url=f"http://{settings.host}:{settings.port}/api/v1",
        restart_required=False,
    )


def update_runtime_config(host: str | None = None, port: int | None = None) -> RuntimeConfigResponse:
    env_path = ENV_FILE
    current_values = _parse_env_lines(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}

    settings = get_settings()
    next_host = host or settings.host
    next_port = port or settings.port

    current_values["HOST"] = next_host
    current_values["PORT"] = str(next_port)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(_serialize_env_lines(current_values), encoding="utf-8")

    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

    return RuntimeConfigResponse(
        host=next_host,
        port=next_port,
        api_base_url=f"http://{next_host}:{next_port}/api/v1",
        restart_required=True,
    )
