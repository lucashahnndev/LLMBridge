import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import AppToken, EnvironmentType, KeyStatus, ProviderKey, UsageLog
from backend.app.routes.usage_logs import list_usage_logs
from backend.app.services.crypto import encrypt_text


class UsageLogFiltersTest(unittest.TestCase):
    def test_usage_logs_filters_by_protocol_and_tool_calling(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "usage-filters.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment=EnvironmentType.DEVELOPMENT,
                    token="app-token-1",
                    is_active=True,
                    rpm_limit=None,
                )
                provider_key = ProviderKey(
                    name="Google primary",
                    description=None,
                    provider="google",
                    encrypted_token=encrypt_text("google-secret"),
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add_all([app_token, provider_key])
                await session.flush()

                session.add_all(
                    [
                        UsageLog(
                            app_token_id=app_token.id,
                            provider_key_id=provider_key.id,
                            protocol_in="openai",
                            protocol_out="openai",
                            route_kind="provider",
                            queue_name=None,
                            model_requested="google/gemini-3.1-flash",
                            provider_used="google",
                            resolved_model="google/gemini-3-flash-preview",
                            prompt_tokens=1,
                            completion_tokens=2,
                            total_tokens=3,
                            latency_ms=10.0,
                            status_code=200,
                            was_rotated=False,
                            tool_calling=True,
                            error_message=None,
                            created_at=datetime.now(timezone.utc),
                        ),
                        UsageLog(
                            app_token_id=app_token.id,
                            provider_key_id=provider_key.id,
                            protocol_in="anthropic",
                            protocol_out="anthropic",
                            route_kind="queue",
                            queue_name="google",
                            model_requested="queue/google",
                            provider_used="google",
                            resolved_model="google/gemini-3-flash-preview",
                            prompt_tokens=4,
                            completion_tokens=5,
                            total_tokens=9,
                            latency_ms=20.0,
                            status_code=200,
                            was_rotated=False,
                            tool_calling=False,
                            error_message=None,
                            created_at=datetime.now(timezone.utc),
                        ),
                    ]
                )
                await session.commit()

                filtered = await list_usage_logs(
                    session=session,
                    app_token_id=app_token.id,
                    provider_key_id=None,
                    queue_name=None,
                    protocol_in="openai",
                    protocol_out="openai",
                    route_kind="provider",
                    tool_calling=True,
                    limit=10,
                    offset=0,
                )

            await engine.dispose()

            self.assertEqual(filtered.total, 1)
            self.assertEqual(len(filtered.items), 1)
            self.assertEqual(filtered.items[0].protocol_in, "openai")
            self.assertTrue(filtered.items[0].tool_calling)


if __name__ == "__main__":
    unittest.main()
