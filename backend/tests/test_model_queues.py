import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import (
    KeyStatus,
    ModelQueue,
    ModelQueueCandidate,
    ProviderKey,
    ProviderKeyRouteState,
    QueueStrategy,
)
from backend.app.services.queues import resolve_model_routes, update_queue_candidate_on_failure, update_queue_candidate_on_success


class ModelQueueServiceTest(unittest.TestCase):
    def test_resolve_model_routes_uses_ordered_strategy(self) -> None:
        asyncio.run(self._run_ordered_test())

    def test_resolve_model_routes_uses_smart_strategy(self) -> None:
        asyncio.run(self._run_smart_test())

    def test_resolve_model_routes_skips_failed_candidate_when_queue_has_multiple_entries(self) -> None:
        asyncio.run(self._run_skip_failed_candidate_test())

    def test_model_not_found_is_penalized_more_than_rate_limit(self) -> None:
        asyncio.run(self._run_not_found_penalty_test())

    def test_queue_resolution_expands_and_balances_provider_keys(self) -> None:
        asyncio.run(self._run_queue_key_balance_test())

    async def _run_ordered_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queues.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                queue = ModelQueue(name="production", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                session.add_all(
                    [
                        ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="first", position=0, score=-3.0),
                        ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="second", position=1, score=10.0),
                        ModelQueueCandidate(queue_id=queue.id, provider="openrouter", model_name="third", position=2, score=5.0),
                        ProviderKey(name="Google first", description=None, provider="google", encrypted_token="g-first", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                        ProviderKey(name="Google second", description=None, provider="google", encrypted_token="g-second", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                        ProviderKey(name="OpenRouter third", description=None, provider="openrouter", encrypted_token="o-third", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                    ]
                )
                await session.commit()

                routes = await resolve_model_routes(session, "queue/production")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], [
                "google/first",
                "google/second",
                "openrouter/third",
                "google/first",
                "google/second",
            ])

    async def _run_smart_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queues-smart.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                queue = ModelQueue(name="smart", description=None, strategy=QueueStrategy.SMART, is_active=True)
                session.add(queue)
                await session.flush()
                low = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="low", position=0, score=-2.0)
                high = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="high", position=5, score=0.5)
                session.add_all([
                    low,
                    high,
                    ProviderKey(name="Google low", description=None, provider="google", encrypted_token="g-low", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                    ProviderKey(name="Google high", description=None, provider="google", encrypted_token="g-high", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                ])
                await session.commit()

                routes = await resolve_model_routes(session, "queue/smart")
                self.assertEqual([route.route for route in routes], ["google/low", "google/high", "google/low", "google/high"])

                await update_queue_candidate_on_failure(session, high, 429, 100.0)
                await update_queue_candidate_on_failure(session, high, 500, 120.0)
                await update_queue_candidate_on_success(session, low, 150.0)
                routes_after = await resolve_model_routes(session, "queue/smart")

            await engine.dispose()

            self.assertEqual([route.route for route in routes_after], ["google/low", "google/high", "google/low", "google/high"])

    async def _run_skip_failed_candidate_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queues-skip.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                queue = ModelQueue(name="fallback", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                session.add_all(
                    [
                        ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="first", position=0, score=0.0),
                        ModelQueueCandidate(queue_id=queue.id, provider="openrouter", model_name="second", position=1, score=0.0),
                        ProviderKey(name="Google first", description=None, provider="google", encrypted_token="g-first", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                        ProviderKey(name="OpenRouter second", description=None, provider="openrouter", encrypted_token="o-second", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                    ]
                )
                await session.commit()

                routes = await resolve_model_routes(session, "queue/fallback")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], ["google/first", "openrouter/second"])

    async def _run_not_found_penalty_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queues-not-found.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                queue = ModelQueue(name="smart-penalty", description=None, strategy=QueueStrategy.SMART, is_active=True)
                session.add(queue)
                await session.flush()
                not_found = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="not-found", position=0, score=0.0)
                rate_limited = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="rate-limited", position=1, score=0.0)
                session.add_all([
                    not_found,
                    rate_limited,
                    ProviderKey(name="Google one", description=None, provider="google", encrypted_token="g-one", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0),
                ])
                await session.commit()

                await update_queue_candidate_on_failure(
                    session,
                    not_found,
                    404,
                    100.0,
                    error_message="models/gemini-2.5-flash-preview is not found",
                )
                await update_queue_candidate_on_failure(
                    session,
                    rate_limited,
                    429,
                    120.0,
                    error_message="Quota exceeded",
                )
                routes = await resolve_model_routes(session, "queue/smart-penalty")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], ["google/rate-limited", "google/not-found"])

    async def _run_queue_key_balance_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "queues-balance.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                queue = ModelQueue(name="gemini", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                candidate = ModelQueueCandidate(
                    queue_id=queue.id,
                    provider="google",
                    model_name="gemini-3-flash-preview",
                    position=0,
                    score=0.0,
                )
                session.add(candidate)
                await session.flush()

                key_one = ProviderKey(
                    name="Key One",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-one",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                key_two = ProviderKey(
                    name="Key Two",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-two",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                key_three = ProviderKey(
                    name="Key Three",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-three",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add_all([key_one, key_two, key_three])
                await session.flush()

                now = datetime(2026, 6, 11, 15, 0, 0, tzinfo=timezone.utc)
                session.add_all(
                    [
                        ProviderKeyRouteState(
                            provider_key_id=key_one.id,
                            provider="google",
                            model_name="gemini-3-flash-preview",
                            in_flight_count=1,
                            last_used_at=now - timedelta(seconds=5),
                        ),
                        ProviderKeyRouteState(
                            provider_key_id=key_two.id,
                            provider="google",
                            model_name="gemini-3-flash-preview",
                            in_flight_count=0,
                            last_used_at=now - timedelta(seconds=10),
                        ),
                        ProviderKeyRouteState(
                            provider_key_id=key_three.id,
                            provider="google",
                            model_name="gemini-3-flash-preview",
                            cooldown_until=datetime(2099, 1, 1, tzinfo=timezone.utc),
                        ),
                    ]
                )
                await session.commit()

                routes = await resolve_model_routes(session, "queue/gemini")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], ["google/gemini-3-flash-preview", "google/gemini-3-flash-preview"])
            self.assertEqual([route.provider_key_name for route in routes], ["Key Two", "Key One"])
            self.assertTrue(all(route.provider_key_id is not None for route in routes))


if __name__ == "__main__":
    unittest.main()
