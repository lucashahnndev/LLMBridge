from __future__ import annotations

import secrets
from pathlib import Path


ENV_PATH = Path("backend/.env")
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./backend/data/database.db"
LEGACY_DATABASE_URL = "sqlite+aiosqlite:///./backend/database.db"
ENV_ORDER = [
    "SECRET_KEY",
    "ADMIN_PASSWORD",
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LOG_FILE_ENABLED",
    "LOG_LEVEL",
    "LOG_FILE_PATH",
    "LOGGING_CONTROL_KEY",
    "TRACE_PROXY_ENABLED",
    "TRACE_PROXY_DIR",
    "TRACE_PROXY_REDACT",
    "HOST",
    "PORT",
]


def generate_secret_key() -> str:
    return secrets.token_urlsafe(32)


def generate_admin_password() -> str:
    return secrets.token_urlsafe(24)


def parse_env(text: str) -> tuple[list[tuple[str, str] | tuple[str, None]], dict[str, str]]:
    entries: list[tuple[str, str] | tuple[str, None]] = []
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            entries.append((line, None))
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        values[key] = value
        entries.append((key, value))
    return entries, values


def render_env(entries: list[tuple[str, str] | tuple[str, None]], values: dict[str, str]) -> str:
    rendered: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        key_or_line, value = entry
        if value is None:
            rendered.append(key_or_line)
            continue
        seen.add(key_or_line)
        rendered.append(f"{key_or_line}={values[key_or_line]}")

    for key in ENV_ORDER:
        if key not in seen:
            rendered.append(f"{key}={values[key]}")

    return "\n".join(rendered).rstrip() + "\n"


def main() -> int:
    existing_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    entries, values = parse_env(existing_text)

    generated_secret = False
    generated_admin = False

    if not values.get("SECRET_KEY", "").strip():
        values["SECRET_KEY"] = generate_secret_key()
        generated_secret = True
    if not values.get("ADMIN_PASSWORD", "").strip():
        values["ADMIN_PASSWORD"] = generate_admin_password()
        generated_admin = True

    database_url = values.get("DATABASE_URL", "").strip()
    if not database_url or database_url == LEGACY_DATABASE_URL:
        values["DATABASE_URL"] = DEFAULT_DATABASE_URL
    if "TELEGRAM_BOT_TOKEN" not in values:
        values["TELEGRAM_BOT_TOKEN"] = ""
    if "TELEGRAM_CHAT_ID" not in values:
        values["TELEGRAM_CHAT_ID"] = ""
    if "LOG_FILE_ENABLED" not in values:
        values["LOG_FILE_ENABLED"] = "false"
    if not values.get("LOG_LEVEL", "").strip():
        values["LOG_LEVEL"] = "INFO"
    if not values.get("LOG_FILE_PATH", "").strip():
        values["LOG_FILE_PATH"] = "logs/backend.log"
    if "LOGGING_CONTROL_KEY" not in values:
        values["LOGGING_CONTROL_KEY"] = ""
    if "TRACE_PROXY_ENABLED" not in values:
        values["TRACE_PROXY_ENABLED"] = "false"
    if not values.get("TRACE_PROXY_DIR", "").strip():
        values["TRACE_PROXY_DIR"] = "traces"
    if "TRACE_PROXY_REDACT" not in values:
        values["TRACE_PROXY_REDACT"] = "true"
    if not values.get("HOST", "").strip():
        values["HOST"] = "127.0.0.1"
    if not values.get("PORT", "").strip():
        values["PORT"] = "8009"

    output = render_env(entries, values)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text(output, encoding="utf-8")

    if generated_secret:
        print("[+] SECRET_KEY gerada automaticamente.")
    if generated_admin:
        print(f"[+] ADMIN_PASSWORD inicial: {values['ADMIN_PASSWORD']}")
    if not generated_secret and not generated_admin:
        print("[*] backend/.env ja estava consistente.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
