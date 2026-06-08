import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import ModelQueue, ModelQueueCandidate, QueueStrategy
from backend.app.services.queues import resolve_model_routes, update_queue_candidate_on_failure, update_queue_candidate_on_success


class ModelQueueServiceTest(unittest.TestCase):
    def test_resolve_model_routes_uses_ordered_strategy(self) -> None:
        asyncio.run(self._run_ordered_test())

    def test_resolve_model_routes_uses_smart_strategy(self) -> None:
        asyncio.run(self._run_smart_test())

    def test_resolve_model_routes_skips_failed_candidate_when_queue_has_multiple_entries(self) -> None:
        asyncio.run(self._run_skip_failed_candidate_test())

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
                    ]
                )
                await session.commit()

                routes = await resolve_model_routes(session, "queue/production")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], [
                "google/first",
                "google/second",
                "openrouter/third",
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
                session.add_all([low, high])
                await session.commit()

                routes = await resolve_model_routes(session, "queue/smart")
                self.assertEqual([route.route for route in routes], ["google/high", "google/low"])

                await update_queue_candidate_on_failure(session, high, 429, 100.0)
                await update_queue_candidate_on_failure(session, high, 500, 120.0)
                await update_queue_candidate_on_success(session, low, 150.0)
                routes_after = await resolve_model_routes(session, "queue/smart")

            await engine.dispose()

            self.assertEqual([route.route for route in routes_after], ["google/low", "google/high"])

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
                    ]
                )
                await session.commit()

                routes = await resolve_model_routes(session, "queue/fallback")

            await engine.dispose()

            self.assertEqual([route.route for route in routes], ["google/first", "openrouter/second"])


if __name__ == "__main__":
    unittest.main()
