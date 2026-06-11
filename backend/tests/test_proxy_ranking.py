import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import KeyStatus, ProviderKey
from backend.app.services.proxy import (
    get_eligible_provider_keys,
    mark_provider_key_model_failure,
    mark_provider_key_model_soft_failure,
)


class ProxyRankingTest(unittest.TestCase):
    def test_eligible_provider_keys_rank_by_model_penalty_then_provider_penalty(self) -> None:
        asyncio.run(self._run_ranking_test())

    def test_soft_failure_increases_model_penalty_without_blocking_key(self) -> None:
        asyncio.run(self._run_soft_failure_test())

    def test_soft_failure_with_cooldown_excludes_problem_model_temporarily(self) -> None:
        asyncio.run(self._run_cooldown_exclusion_test())

    async def _run_ranking_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ranking.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                provider_key_low = ProviderKey(
                    name="Low",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-low",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                    updated_at=datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc),
                )
                provider_key_mid = ProviderKey(
                    name="Mid",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-mid",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                    updated_at=datetime(2026, 6, 8, 0, 0, 1, tzinfo=timezone.utc),
                )
                provider_key_high = ProviderKey(
                    name="High",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-high",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                    updated_at=datetime(2026, 6, 8, 0, 0, 2, tzinfo=timezone.utc),
                )
                session.add_all([provider_key_low, provider_key_mid, provider_key_high])
                await session.flush()

                await mark_provider_key_model_failure(session, provider_key_high, "gemini-3-flash-preview", retry_after_seconds=60)
                await mark_provider_key_model_soft_failure(session, provider_key_mid, "gemini-3-flash-preview")
                await mark_provider_key_model_soft_failure(session, provider_key_mid, "gemini-3-flash-preview")

                eligible = await get_eligible_provider_keys(session, "google", "gemini-3-flash-preview")

            await engine.dispose()

            self.assertEqual([provider_key.id for provider_key in eligible], [provider_key_low.id, provider_key_mid.id])

    async def _run_soft_failure_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "soft-failure.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                provider_key = ProviderKey(
                    name="Penalty",
                    description=None,
                    provider="google",
                    encrypted_token="cipher",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add(provider_key)
                await session.flush()

                await mark_provider_key_model_soft_failure(session, provider_key, "gemini-3-flash-preview")
                eligible = await get_eligible_provider_keys(session, "google", "gemini-3-flash-preview")

            await engine.dispose()

            self.assertEqual(len(eligible), 1)
            self.assertEqual(eligible[0].id, provider_key.id)

    async def _run_cooldown_exclusion_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "cooldown-exclusion.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                healthy_key = ProviderKey(
                    name="Healthy",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-healthy",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                blocked_key = ProviderKey(
                    name="Blocked",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-blocked",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add_all([healthy_key, blocked_key])
                await session.flush()

                await mark_provider_key_model_soft_failure(
                    session,
                    blocked_key,
                    "gemini-3-flash-preview",
                    cooldown_seconds=3600,
                )

                eligible = await get_eligible_provider_keys(session, "google", "gemini-3-flash-preview")

            await engine.dispose()

            self.assertEqual([key.id for key in eligible], [healthy_key.id])


if __name__ == "__main__":
    unittest.main()
