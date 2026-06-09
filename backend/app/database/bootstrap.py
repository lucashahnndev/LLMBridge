from sqlalchemy import inspect, text

from backend.app.database.base import Base
from backend.app.database.models import (  # noqa: F401
    AppToken,
    AdminTokenRevocation,
    AlertSettings,
    ModelQueue,
    ModelQueueCandidate,
    ProviderKey,
    ProviderKeyModelCooldown,
    SchemaVersion,
    UsageLog,
)
from backend.app.database.migrations import apply_schema_migrations
from backend.app.database.session import get_engine


async def ensure_usage_log_telemetry_columns(engine) -> None:
    async with engine.begin() as conn:
        def _ensure(sync_conn):
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

        await conn.run_sync(_ensure)


async def ensure_database() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await apply_schema_migrations(engine)
