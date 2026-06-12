import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.version import SCHEMA_VERSION
from backend.app.database.migrations import apply_schema_migrations


class DatabaseMigrationTest(unittest.TestCase):
    def test_apply_schema_migrations_upgrades_schema_version_and_usage_log_columns(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "migrations.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE usage_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        app_token_id INTEGER NOT NULL,
                        provider_key_id INTEGER,
                        model_requested VARCHAR(100) NOT NULL,
                        provider_used VARCHAR(50) NOT NULL,
                        resolved_model VARCHAR(120),
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        latency_ms FLOAT NOT NULL,
                        status_code INTEGER NOT NULL,
                        was_rotated INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE schema_versions (
                        "key" VARCHAR(32) PRIMARY KEY NOT NULL,
                        version VARCHAR(20) NOT NULL,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.exec_driver_sql(
                    "INSERT INTO schema_versions (\"key\", version) VALUES ('schema', '0.1.0')"
                )

            applied = await apply_schema_migrations(engine)
            self.assertEqual(applied, ["0.3.0", "0.3.1", SCHEMA_VERSION])

            async with engine.begin() as conn:
                columns = await conn.exec_driver_sql("PRAGMA table_info(usage_logs)")
                column_names = {row[1] for row in columns.fetchall()}
                self.assertIn("protocol_in", column_names)
                self.assertIn("protocol_out", column_names)
                self.assertIn("route_kind", column_names)
                self.assertIn("tool_calling", column_names)

                route_state_columns = await conn.exec_driver_sql("PRAGMA table_info(provider_key_route_states)")
                route_state_column_names = {row[1] for row in route_state_columns.fetchall()}
                self.assertIn("provider_key_id", route_state_column_names)
                self.assertIn("provider", route_state_column_names)
                self.assertIn("model_name", route_state_column_names)
                self.assertIn("cooldown_until", route_state_column_names)
                self.assertIn("blocked_until", route_state_column_names)
                self.assertIn("disabled", route_state_column_names)
                self.assertIn("disabled_reason", route_state_column_names)
                self.assertIn("last_used_at", route_state_column_names)
                self.assertIn("in_flight_count", route_state_column_names)
                self.assertIn("soft_reserved_until", route_state_column_names)
                self.assertIn("next_available_at", route_state_column_names)

                queue_candidate_columns = await conn.exec_driver_sql("PRAGMA table_info(model_queue_candidates)")
                queue_candidate_column_names = {row[1] for row in queue_candidate_columns.fetchall()}
                self.assertIn("base_degradation", queue_candidate_column_names)
                self.assertIn("latency_score", queue_candidate_column_names)
                self.assertIn("error_score", queue_candidate_column_names)
                self.assertIn("final_rank", queue_candidate_column_names)

                queue_result = await conn.exec_driver_sql(
                    "SELECT id FROM model_queues WHERE name = 'gemini'"
                )
                queue_row = queue_result.fetchone()
                self.assertIsNotNone(queue_row)
                if queue_row is not None:
                    candidate_result = await conn.exec_driver_sql(
                        """
                        SELECT provider, model_name
                        FROM model_queue_candidates
                        WHERE queue_id = ?
                        ORDER BY position ASC, id ASC
                        """,
                        (queue_row[0],),
                    )
                    candidates = candidate_result.fetchall()
                    self.assertEqual([candidate[0] for candidate in candidates], ["google"] * 8)
                    self.assertEqual(
                        [candidate[1] for candidate in candidates],
                        [
                            "gemini-2.5-pro",
                            "gemini-3-flash-preview",
                            "gemini-2.5-flash",
                            "gemini-flash-latest",
                            "gemini-3.1-flash-lite",
                            "gemini-2.5-flash-lite",
                            "gemini-flash-lite-latest",
                            "gemini-3.1-flash-live-preview",
                        ],
                    )

                version_result = await conn.exec_driver_sql(
                    "SELECT version FROM schema_versions WHERE \"key\" = 'schema'"
                )
                self.assertEqual(version_result.scalar_one(), SCHEMA_VERSION)

            await engine.dispose()

    def test_apply_schema_migrations_backfills_legacy_model_cooldowns_into_route_state(self) -> None:
        asyncio.run(self._run_backfill())

    async def _run_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "migrations-backfill.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

            async with engine.begin() as conn:
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE provider_keys (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        description TEXT,
                        provider VARCHAR(50) NOT NULL,
                        encrypted_token TEXT NOT NULL,
                        status TEXT NOT NULL,
                        blocked_until DATETIME,
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE provider_key_model_cooldowns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider_key_id INTEGER NOT NULL,
                        model_name VARCHAR(120) NOT NULL,
                        blocked_until DATETIME NOT NULL,
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE schema_versions (
                        "key" VARCHAR(32) PRIMARY KEY NOT NULL,
                        version VARCHAR(20) NOT NULL,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.exec_driver_sql(
                    """
                    INSERT INTO provider_keys (id, name, description, provider, encrypted_token, status, blocked_until, failure_count)
                    VALUES (1, 'Google Key', NULL, 'google', 'cipher', 'ACTIVE', NULL, 0)
                    """
                )
                await conn.exec_driver_sql(
                    """
                    INSERT INTO provider_key_model_cooldowns (provider_key_id, model_name, blocked_until, failure_count)
                    VALUES (1, 'gemini-3-flash-preview', '2026-06-11 10:00:00', 3)
                    """
                )
                await conn.exec_driver_sql(
                    "INSERT INTO schema_versions (\"key\", version) VALUES ('schema', '0.3.0')"
                )

            applied = await apply_schema_migrations(engine)
            self.assertEqual(applied, ["0.3.1", SCHEMA_VERSION])

            async with engine.begin() as conn:
                rows = await conn.exec_driver_sql(
                    """
                    SELECT provider_key_id, provider, model_name, cooldown_until, disabled, in_flight_count
                    FROM provider_key_route_states
                    """
                )
                route_state = rows.fetchone()
                self.assertIsNotNone(route_state)
                if route_state is not None:
                    self.assertEqual(route_state[0], 1)
                    self.assertEqual(route_state[1], "google")
                    self.assertEqual(route_state[2], "gemini-3-flash-preview")
                    self.assertTrue(str(route_state[3]).startswith("2026-06-11 10:00:00"))
                    self.assertEqual(route_state[4], 0)
                    self.assertEqual(route_state[5], 0)

            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
