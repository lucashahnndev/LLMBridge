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
            self.assertEqual(applied, [SCHEMA_VERSION])

            async with engine.begin() as conn:
                columns = await conn.exec_driver_sql("PRAGMA table_info(usage_logs)")
                column_names = {row[1] for row in columns.fetchall()}
                self.assertIn("protocol_in", column_names)
                self.assertIn("protocol_out", column_names)
                self.assertIn("route_kind", column_names)
                self.assertIn("tool_calling", column_names)

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


if __name__ == "__main__":
    unittest.main()
