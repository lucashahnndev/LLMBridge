from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import inspect, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.core.version import SCHEMA_BASE_VERSION, SCHEMA_VERSION, compare_semver
from backend.app.database.models import (
    AlertSettings,
    ModelQueue,
    ModelQueueCandidate,
    ProviderKey,
    ProviderModelRouteScore,
    ProviderKeyRouteState,
    QueueStrategy,
    SchemaVersion,
)
from backend.app.core.config import get_settings
from backend.app.services.crypto import encrypt_text


SchemaUpgrade = Callable[[object], None]


def _coerce_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


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
    if "upstream_protocol" not in existing_columns:
        additions.append(("upstream_protocol", "TEXT NOT NULL DEFAULT 'openai'"))
    if "route_kind" not in existing_columns:
        additions.append(("route_kind", "TEXT NOT NULL DEFAULT 'provider'"))
    if "tool_calling" not in existing_columns:
        additions.append(("tool_calling", "INTEGER NOT NULL DEFAULT 0"))

    for column_name, column_def in additions:
        sync_conn.execute(text(f"ALTER TABLE usage_logs ADD COLUMN {column_name} {column_def}"))


def _ensure_model_queue_rank_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "model_queue_candidates" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("model_queue_candidates")}
    additions: list[tuple[str, str]] = []
    if "base_degradation" not in existing_columns:
        additions.append(("base_degradation", "FLOAT NOT NULL DEFAULT 0"))
    if "latency_score" not in existing_columns:
        additions.append(("latency_score", "FLOAT NOT NULL DEFAULT 0"))
    if "error_score" not in existing_columns:
        additions.append(("error_score", "FLOAT NOT NULL DEFAULT 0"))
    if "final_rank" not in existing_columns:
        additions.append(("final_rank", "FLOAT NOT NULL DEFAULT 0"))

    for column_name, column_def in additions:
        sync_conn.execute(text(f"ALTER TABLE model_queue_candidates ADD COLUMN {column_name} {column_def}"))

    sync_conn.execute(
        text(
            """
            UPDATE model_queue_candidates
            SET final_rank = score
            WHERE final_rank IS NULL OR final_rank = 0
            """
        )
    )


def _ensure_provider_key_route_state_rank_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "provider_key_route_states" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("provider_key_route_states")}
    additions: list[tuple[str, str]] = []
    if "base_degradation" not in existing_columns:
        additions.append(("base_degradation", "FLOAT NOT NULL DEFAULT 0"))
    if "latency_score" not in existing_columns:
        additions.append(("latency_score", "FLOAT NOT NULL DEFAULT 0"))
    if "error_score" not in existing_columns:
        additions.append(("error_score", "FLOAT NOT NULL DEFAULT 0"))
    if "final_rank" not in existing_columns:
        additions.append(("final_rank", "FLOAT NOT NULL DEFAULT 0"))
    if "score" not in existing_columns:
        additions.append(("score", "FLOAT NOT NULL DEFAULT 0"))
    if "failure_count" not in existing_columns:
        additions.append(("failure_count", "INTEGER NOT NULL DEFAULT 0"))
    if "success_count" not in existing_columns:
        additions.append(("success_count", "INTEGER NOT NULL DEFAULT 0"))
    if "avg_latency_ms" not in existing_columns:
        additions.append(("avg_latency_ms", "FLOAT NOT NULL DEFAULT 0"))

    for column_name, column_def in additions:
        sync_conn.execute(text(f"ALTER TABLE provider_key_route_states ADD COLUMN {column_name} {column_def}"))

    sync_conn.execute(
        text(
            """
            UPDATE provider_key_route_states
            SET final_rank = score
            WHERE final_rank IS NULL OR final_rank = 0
            """
        )
    )


def _ensure_provider_model_route_score_table(sync_conn) -> None:
    _ensure_tables(sync_conn, ProviderModelRouteScore.__table__)


def _ensure_tables(sync_conn, *tables) -> None:
    for table in tables:
        table.create(sync_conn, checkfirst=True)


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

DEFAULT_GITHUB_QUEUE_NAME = "github"
DEFAULT_GITHUB_QUEUE_DESCRIPTION = "Default GitHub Models queue"
DEFAULT_GITHUB_QUEUE_MODELS = (
    "openai/gpt-5",
    "openai/o3",
    "openai/o1",
    "openai/gpt-4.1",
    "openai/gpt-5-chat",
    "openai/gpt-5-mini",
    "openai/o4-mini",
    "openai/o3-mini",
    "openai/o1-preview",
    "openai/o1-mini",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
    "openai/gpt-5-nano",
    "microsoft/phi-4-reasoning",
    "microsoft/phi-4-multimodal-instruct",
    "microsoft/phi-4-mini-reasoning",
    "microsoft/phi-4-mini-instruct",
    "microsoft/phi-4",
    "meta/llama-4-maverick-17b-128e-instruct-fp8",
    "meta/llama-4-scout-17b-16e-instruct",
    "deepseek/deepseek-r1",
    "deepseek/deepseek-r1-0528",
    "deepseek/deepseek-v3-0324",
    "mistral-ai/mistral-medium-2505",
    "mistral-ai/mistral-small-2503",
    "mistral-ai/codestral-2501",
    "cohere/cohere-command-a",
    "meta/meta-llama-3.1-405b-instruct",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "meta/llama-3.2-11b-vision-instruct",
    "meta/meta-llama-3.1-8b-instruct",
    "mistral-ai/ministral-3b",
    "openai/text-embedding-3-large",
    "openai/text-embedding-3-small",
)

DEFAULT_OPENROUTER_QUEUE_NAME = "openrouter"
DEFAULT_OPENROUTER_QUEUE_DESCRIPTION = "Default OpenRouter queue"
DEFAULT_OPENROUTER_QUEUE_MODELS = (
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "deepseek/deepseek-r1-0528",
    "deepseek/deepseek-r1",
    "meta-llama/llama-3.3-70b-instruct",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-large-2512",
    "mistralai/mistral-medium-3.1",
    "mistralai/mistral-small-3.2-24b-instruct",
    "microsoft/phi-4",
    "microsoft/phi-4-mini-instruct",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.2-3b-instruct:free",
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


def _seed_default_github_queue(sync_conn) -> None:
    existing_queue = sync_conn.execute(
        select(ModelQueue.__table__.c.id).where(ModelQueue.__table__.c.name == DEFAULT_GITHUB_QUEUE_NAME)
    ).scalar_one_or_none()
    if existing_queue is not None:
        return

    result = sync_conn.execute(
        insert(ModelQueue.__table__).values(
            name=DEFAULT_GITHUB_QUEUE_NAME,
            description=DEFAULT_GITHUB_QUEUE_DESCRIPTION,
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
                "provider": "github",
                "model_name": model_name.strip(),
                "position": position,
                "is_active": True,
            }
            for position, model_name in enumerate(DEFAULT_GITHUB_QUEUE_MODELS)
        ],
    )


def _seed_default_openrouter_queue(sync_conn) -> None:
    existing_queue = sync_conn.execute(
        select(ModelQueue.__table__.c.id).where(ModelQueue.__table__.c.name == DEFAULT_OPENROUTER_QUEUE_NAME)
    ).scalar_one_or_none()
    if existing_queue is not None:
        return

    result = sync_conn.execute(
        insert(ModelQueue.__table__).values(
            name=DEFAULT_OPENROUTER_QUEUE_NAME,
            description=DEFAULT_OPENROUTER_QUEUE_DESCRIPTION,
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
                "provider": "openrouter",
                "model_name": model_name.strip(),
                "position": position,
                "is_active": True,
            }
            for position, model_name in enumerate(DEFAULT_OPENROUTER_QUEUE_MODELS)
        ],
    )


def _upgrade_telemetry_and_seed_gemini_queue(sync_conn) -> None:
    _ensure_tables(sync_conn, ModelQueue.__table__, ModelQueueCandidate.__table__)
    _ensure_usage_log_telemetry_columns(sync_conn)
    _seed_default_gemini_queue(sync_conn)


def _upgrade_seed_github_queue(sync_conn) -> None:
    _ensure_tables(sync_conn, ModelQueue.__table__, ModelQueueCandidate.__table__)
    _seed_default_github_queue(sync_conn)


def _upgrade_seed_openrouter_queue(sync_conn) -> None:
    _ensure_tables(sync_conn, ModelQueue.__table__, ModelQueueCandidate.__table__)
    _seed_default_openrouter_queue(sync_conn)


def _upgrade_seed_and_reorder_openrouter_queue(sync_conn) -> None:
    _upgrade_seed_openrouter_queue(sync_conn)
    _reorder_default_openrouter_queue(sync_conn)


def _reorder_default_github_queue(sync_conn) -> None:
    queue_id = sync_conn.execute(
        select(ModelQueue.__table__.c.id).where(ModelQueue.__table__.c.name == DEFAULT_GITHUB_QUEUE_NAME)
    ).scalar_one_or_none()
    if queue_id is None:
        return

    current_rows = sync_conn.execute(
        select(
            ModelQueueCandidate.__table__.c.id,
            ModelQueueCandidate.__table__.c.provider,
            ModelQueueCandidate.__table__.c.model_name,
        ).where(ModelQueueCandidate.__table__.c.queue_id == queue_id)
    ).fetchall()
    current_by_key = {(row[2],): row[0] for row in current_rows}

    for position, model_name in enumerate(DEFAULT_GITHUB_QUEUE_MODELS):
        candidate_id = current_by_key.get((model_name.strip(),))
        if candidate_id is None:
            continue
        sync_conn.execute(
            ModelQueueCandidate.__table__.update()
            .where(ModelQueueCandidate.__table__.c.id == candidate_id)
            .values(position=position)
        )


def _reorder_default_openrouter_queue(sync_conn) -> None:
    queue_id = sync_conn.execute(
        select(ModelQueue.__table__.c.id).where(ModelQueue.__table__.c.name == DEFAULT_OPENROUTER_QUEUE_NAME)
    ).scalar_one_or_none()
    if queue_id is None:
        return

    current_rows = sync_conn.execute(
        select(
            ModelQueueCandidate.__table__.c.id,
            ModelQueueCandidate.__table__.c.provider,
            ModelQueueCandidate.__table__.c.model_name,
        ).where(ModelQueueCandidate.__table__.c.queue_id == queue_id)
    ).fetchall()
    current_by_key = {(row[2],): row[0] for row in current_rows}

    for position, model_name in enumerate(DEFAULT_OPENROUTER_QUEUE_MODELS):
        candidate_id = current_by_key.get((model_name.strip(),))
        if candidate_id is None:
            continue
        sync_conn.execute(
            ModelQueueCandidate.__table__.update()
            .where(ModelQueueCandidate.__table__.c.id == candidate_id)
            .values(position=position)
        )


def _seed_default_alert_settings(sync_conn) -> None:
    existing = sync_conn.execute(
        select(AlertSettings.__table__.c.key).where(AlertSettings.__table__.c.key == "global")
    ).scalar_one_or_none()
    if existing is not None:
        return

    settings = get_settings()
    telegram_token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
    telegram_chat_id = settings.telegram_chat_id.strip() if settings.telegram_chat_id else ""

    sync_conn.execute(
        insert(AlertSettings.__table__).values(
            key="global",
            telegram_enabled=bool(telegram_token and telegram_chat_id),
            telegram_bot_token_encrypted=encrypt_text(telegram_token) if telegram_token else None,
            telegram_chat_id=telegram_chat_id or None,
            alert_proxy_failures=True,
            alert_queue_exhausted=True,
            alert_provider_pool_exhausted=True,
            alert_provider_key_status_changes=True,
        )
    )


def _upgrade_alert_settings(sync_conn) -> None:
    _ensure_tables(sync_conn, AlertSettings.__table__)
    _upgrade_telemetry_and_seed_gemini_queue(sync_conn)
    _seed_default_alert_settings(sync_conn)


def _upgrade_provider_key_route_states(sync_conn) -> None:
    _ensure_tables(sync_conn, ProviderKeyRouteState.__table__)
    _ensure_provider_key_route_state_rank_columns(sync_conn)

    inspector = inspect(sync_conn)
    if "provider_key_model_cooldowns" not in inspector.get_table_names():
        return

    existing_rows = sync_conn.execute(
        select(
            ProviderKeyRouteState.__table__.c.provider_key_id,
            ProviderKeyRouteState.__table__.c.provider,
            ProviderKeyRouteState.__table__.c.model_name,
        )
    ).fetchall()
    existing_keys = {(row[0], row[1], row[2]) for row in existing_rows}

    legacy_rows = sync_conn.execute(
        text(
            """
            SELECT
                pkmc.provider_key_id,
                pk.provider,
                pkmc.model_name,
                pkmc.blocked_until,
                pkmc.created_at,
                pkmc.updated_at
            FROM provider_key_model_cooldowns pkmc
            JOIN provider_keys pk ON pk.id = pkmc.provider_key_id
            """
        )
    ).fetchall()

    inserts: list[dict[str, object]] = []
    for row in legacy_rows:
        composite_key = (row[0], row[1], row[2])
        if composite_key in existing_keys:
            continue
        inserts.append(
            {
                "provider_key_id": row[0],
                "provider": row[1],
                "model_name": row[2],
                "cooldown_until": _coerce_datetime(row[3]),
                "blocked_until": None,
                "disabled": False,
                "disabled_reason": None,
                "last_used_at": None,
                "in_flight_count": 0,
                "soft_reserved_until": None,
                "next_available_at": None,
                "created_at": _coerce_datetime(row[4]),
                "updated_at": _coerce_datetime(row[5]),
            }
        )

    if inserts:
        sync_conn.execute(insert(ProviderKeyRouteState.__table__), inserts)


def _upgrade_provider_model_route_scores(sync_conn) -> None:
    _ensure_provider_model_route_score_table(sync_conn)
    _ensure_provider_key_route_state_rank_columns(sync_conn)

    inspector = inspect(sync_conn)
    if "provider_key_route_states" not in inspector.get_table_names():
        return

    existing_rows = sync_conn.execute(
        select(
            ProviderModelRouteScore.__table__.c.provider,
            ProviderModelRouteScore.__table__.c.model_name,
        )
    ).fetchall()
    existing_keys = {(row[0], row[1]) for row in existing_rows}

    source_rows = sync_conn.execute(
        text(
            """
            SELECT
                provider,
                model_name,
                AVG(latency_score) AS latency_score,
                AVG(error_score) AS error_score,
                AVG(final_rank) AS final_rank,
                AVG(score) AS score,
                SUM(failure_count) AS failure_count,
                SUM(success_count) AS success_count,
                AVG(avg_latency_ms) AS avg_latency_ms
            FROM provider_key_route_states
            GROUP BY provider, model_name
            """
        )
    ).fetchall()

    inserts: list[dict[str, object]] = []
    for row in source_rows:
        composite_key = (row[0], row[1])
        if composite_key in existing_keys:
            continue
        inserts.append(
            {
                "provider": row[0],
                "model_name": row[1],
                "latency_score": float(row[2] or 0.0),
                "error_score": float(row[3] or 0.0),
                "final_rank": float(row[4] or 0.0),
                "score": float(row[5] or 0.0),
                "failure_count": int(row[6] or 0),
                "success_count": int(row[7] or 0),
                "avg_latency_ms": float(row[8] or 0.0),
            }
        )

    if inserts:
        sync_conn.execute(insert(ProviderModelRouteScore.__table__), inserts)


def _upgrade_model_queue_rank_fields(sync_conn) -> None:
    _ensure_model_queue_rank_columns(sync_conn)


def _upgrade_usage_log_upstream_protocol(sync_conn) -> None:
    _ensure_usage_log_telemetry_columns(sync_conn)


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
        version="0.3.0",
        description="Add telemetry columns, seed Gemini queue, and initialize alert settings",
        upgrade=_upgrade_alert_settings,
    ),
    MigrationStep(
        version="0.3.1",
        description="Add provider-key route operational state for key/provider/model availability",
        upgrade=_upgrade_provider_key_route_states,
    ),
    MigrationStep(
        version="0.3.2",
        description="Add provider/model rank fields for queue candidates",
        upgrade=_upgrade_model_queue_rank_fields,
    ),
    MigrationStep(
        version="0.3.4",
        description="Seed GitHub Models queue",
        upgrade=_upgrade_seed_github_queue,
    ),
    MigrationStep(
        version="0.3.6",
        description="Add upstream protocol telemetry for usage logs",
        upgrade=_upgrade_usage_log_upstream_protocol,
    ),
    MigrationStep(
        version="0.3.7",
        description="Reorder GitHub Models queue by capability",
        upgrade=_reorder_default_github_queue,
    ),
    MigrationStep(
        version="0.3.8",
        description="Seed OpenRouter queue and reorder by capability",
        upgrade=_upgrade_seed_and_reorder_openrouter_queue,
    ),
    MigrationStep(
        version="0.3.9",
        description="Add global provider/model route scores",
        upgrade=_upgrade_provider_model_route_scores,
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
