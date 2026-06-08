import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import AppToken, EnvironmentType, KeyStatus, ProviderKey, UsageLog
from backend.app.services.metrics import build_timeseries_metrics


class MetricsTimeseriesTest(unittest.TestCase):
    def test_build_timeseries_metrics_groups_usage_logs(self) -> None:
        asyncio.run(self._run_test())

    async def _run_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "metrics.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            now = datetime.now(timezone.utc)
            three_days_ago = now - timedelta(days=3)
            yesterday = now - timedelta(days=1)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment=EnvironmentType.DEVELOPMENT,
                    token="lk-key-test",
                    is_active=True,
                    rpm_limit=None,
                )
                provider_key = ProviderKey(
                    name="Gemini",
                    description=None,
                    provider="google",
                    encrypted_token="cipher",
                    status=KeyStatus.ACTIVE,
                )
                session.add_all([app_token, provider_key])
                await session.flush()

                session.add_all(
                    [
                        UsageLog(
                            app_token_id=app_token.id,
                            provider_key_id=provider_key.id,
                            model_requested="google/gemini-3.1-flash",
                            provider_used="google",
                            prompt_tokens=10,
                            completion_tokens=5,
                            total_tokens=15,
                            latency_ms=120.5,
                            status_code=200,
                            was_rotated=False,
                            error_message=None,
                            created_at=three_days_ago,
                        ),
                        UsageLog(
                            app_token_id=app_token.id,
                            provider_key_id=provider_key.id,
                            model_requested="google/gemini-3.1-flash",
                            provider_used="google",
                            prompt_tokens=12,
                            completion_tokens=6,
                            total_tokens=18,
                            latency_ms=220.0,
                            status_code=429,
                            was_rotated=True,
                            error_message="rate limited",
                            created_at=yesterday,
                        ),
                    ]
                )
                await session.commit()

                result = await build_timeseries_metrics(session, "7d")

            await engine.dispose()

            self.assertEqual(result.window, "7d")
            self.assertEqual(result.granularity, "day")
            self.assertGreaterEqual(len(result.buckets), 7)

            bucket_by_day = {bucket.bucket_start[:10]: bucket for bucket in result.buckets}
            self.assertEqual(bucket_by_day[three_days_ago.date().isoformat()].requests_count, 1)
            self.assertEqual(bucket_by_day[three_days_ago.date().isoformat()].success_count, 1)
            self.assertEqual(bucket_by_day[three_days_ago.date().isoformat()].total_tokens_consumed, 15)
            self.assertEqual(bucket_by_day[yesterday.date().isoformat()].requests_count, 1)
            self.assertEqual(bucket_by_day[yesterday.date().isoformat()].error_count, 1)
            self.assertEqual(bucket_by_day[yesterday.date().isoformat()].total_rotations_triggered, 1)


if __name__ == "__main__":
    unittest.main()
