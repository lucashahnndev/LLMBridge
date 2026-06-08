from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.core.version import SCHEMA_BASE_VERSION, SCHEMA_VERSION, compare_semver
from backend.app.database.models import ModelQueue, ModelQueueCandidate, QueueStrategy, SchemaVersion


SchemaUpgrade = Callable[[object], None]


@dataclass(frozen=True)
class MigrationStep:
    version: str
    description: str
    upgrade: SchemaUpgrade


def _ensure_usage_log_telemetry_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "usage_logs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("usage_logs")}
    additions: list[tuple[str, str]] = []
    if "protocol_in" not in existing_columns:
        additions.append(("protocol_in", "TEXT NOT NULL DEFAULT 'openai'"))
    if "protocol_out" not in existing_columns:
        additions.append(("protocol_out", "TEXT NOT NULL DEFAULT 'openai'"))
    if "route_kind" not in existing_columns:
        additions.append(("route_kind", "TEXT NOT NULL DEFAULT 'provider'"))
    if "tool_calling" not in existing_columns:
        additions.append(("tool_calling", "INTEGER NOT NULL DEFAULT 0"))

    for column_name, column_def in additions:
        sync_conn.execute(text(f"ALTER TABLE usage_logs ADD COLUMN {column_name} {column_def}"))


DEFAULT_GEMINI_QUEUE_NAME = "gemini"
DEFAULT_GEMINI_QUEUE_DESCRIPTION = "Default Gemini fallback queue"
DEFAULT_GEMINI_QUEUE_MODELS = (
    "models/gemini-2.5-pro",
    "models/gemini-3-flash-preview",
    "models/gemini-2.5-flash",
    "models/gemini-flash-latest",
    "models/gemini-3.1-flash-lite",
    "models/gemini-2.5-flash-lite",
    "models/gemini-flash-lite-latest",
    "models/gemini-3.1-flash-live-preview",
)


def _normalize_model_name(model_name: str) -> str:
    cleaned = model_name.strip()
    if cleaned.startswith("models/"):
        return cleaned.split("/", 1)[1]
    return cleaned


def _seed_default_gemini_queue(sync_conn) -> None:
    existing_queue = sync_conn.execute(
        select(ModelQueue.__table__.c.id).where(ModelQueue.__table__.c.name == DEFAULT_GEMINI_QUEUE_NAME)
    ).scalar_one_or_none()
    if existing_queue is not None:
        return

    result = sync_conn.execute(
        insert(ModelQueue.__table__).values(
            name=DEFAULT_GEMINI_QUEUE_NAME,
            description=DEFAULT_GEMINI_QUEUE_DESCRIPTION,
            strategy=QueueStrategy.ORDERED,
            is_active=True,
        )
    )
    queue_id = result.inserted_primary_key[0]

    sync_conn.execute(
        insert(ModelQueueCandidate.__table__),
        [
            {
                "queue_id": queue_id,
                "provider": "google",
                "model_name": _normalize_model_name(model_name),
                "position": position,
                "is_active": True,
            }
            for position, model_name in enumerate(DEFAULT_GEMINI_QUEUE_MODELS)
        ],
    )


def _upgrade_telemetry_and_seed_gemini_queue(sync_conn) -> None:
    _ensure_usage_log_telemetry_columns(sync_conn)
    _seed_default_gemini_queue(sync_conn)


def _read_schema_version(sync_conn) -> str:
    version = sync_conn.execute(
        select(SchemaVersion.version).where(SchemaVersion.key == "schema")
    ).scalar_one_or_none()
    return version or SCHEMA_BASE_VERSION


def _write_schema_version(sync_conn, version: str) -> None:
    existing = sync_conn.execute(
        select(SchemaVersion).where(SchemaVersion.key == "schema")
    ).scalar_one_or_none()
    if existing is None:
        sync_conn.execute(SchemaVersion.__table__.insert().values(key="schema", version=version))
    else:
        sync_conn.execute(
            SchemaVersion.__table__.update().where(SchemaVersion.key == "schema").values(version=version)
        )


MIGRATION_STEPS: tuple[MigrationStep, ...] = (
    MigrationStep(
        version=SCHEMA_VERSION,
        description="Add usage log telemetry columns and seed default Gemini queue",
        upgrade=_upgrade_telemetry_and_seed_gemini_queue,
    ),
)


async def apply_schema_migrations(engine: AsyncEngine) -> list[str]:
    applied: list[str] = []

    async with engine.begin() as conn:
        def _apply(sync_conn) -> list[str]:
            current_version = _read_schema_version(sync_conn)
            completed: list[str] = []
            for step in MIGRATION_STEPS:
                if compare_semver(step.version, current_version) <= 0:
                    continue
                step.upgrade(sync_conn)
                _write_schema_version(sync_conn, step.version)
                current_version = step.version
                completed.append(step.version)
            if not completed:
                _write_schema_version(sync_conn, current_version)
            return completed

        applied = await conn.run_sync(_apply)

    return applied
