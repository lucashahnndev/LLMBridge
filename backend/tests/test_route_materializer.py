import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import KeyStatus, ModelQueue, ModelQueueCandidate, ProviderKey, ProviderKeyRouteState, QueueStrategy
from backend.app.services.queues import materialize_model_route_snapshot
from backend.app.services.route_materializer import (
    apply_materialized_route_unavailability,
    get_route_materializer,
    invalidate_materialized_route_snapshot,
    ensure_materialized_route_snapshot,
)


class RouteMaterializerTest(unittest.TestCase):
    def test_cached_exhausted_snapshot_raises_retry_after(self) -> None:
        asyncio.run(self._run_cached_exhausted_snapshot_test())

    def test_cached_snapshot_removes_unavailable_route_immediately(self) -> None:
        asyncio.run(self._run_cached_snapshot_patch_test())

    def test_materialized_queue_routes_use_operational_model_name_for_aliases(self) -> None:
        asyncio.run(self._run_alias_materialization_test())

    async def _run_cached_exhausted_snapshot_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route-materializer.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            try:
                async with session_factory() as session:
                    queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                    session.add(queue)
                    await session.flush()
                    session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0))
                    await session.flush()

                    key = ProviderKey(
                        name="Key A",
                        description=None,
                        provider="google",
                        encrypted_token="cipher-a",
                        status=KeyStatus.ACTIVE,
                        blocked_until=None,
                        failure_count=0,
                    )
                    session.add(key)
                    await session.flush()
                    session.add(
                        ProviderKeyRouteState(
                            provider_key_id=key.id,
                            provider="google",
                            model_name="flash",
                            cooldown_until=datetime.now(timezone.utc) + timedelta(seconds=90),
                        )
                    )
                    await session.commit()

                    snapshot = await materialize_model_route_snapshot(session, "queue/prod")
                    self.assertEqual(snapshot.routes, [])
                    self.assertEqual(snapshot.summary.recoverable_cooldowns, 1)

                    materializer = get_route_materializer()
                    invalidate_materialized_route_snapshot("queue/prod")
                    materializer.set_snapshot("queue/prod", snapshot)

                    with self.assertRaises(HTTPException) as ctx:
                        await ensure_materialized_route_snapshot(session, "queue/prod")

                self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                self.assertIn("Retry-After", ctx.exception.headers)
            finally:
                invalidate_materialized_route_snapshot("queue/prod")
                await engine.dispose()

    async def _run_cached_snapshot_patch_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route-materializer-patch.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            try:
                async with session_factory() as session:
                    queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                    session.add(queue)
                    await session.flush()
                    session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0))
                    await session.flush()

                    key_one = ProviderKey(
                        name="Key A",
                        description=None,
                        provider="google",
                        encrypted_token="cipher-a",
                        status=KeyStatus.ACTIVE,
                        blocked_until=None,
                        failure_count=0,
                    )
                    key_two = ProviderKey(
                        name="Key B",
                        description=None,
                        provider="google",
                        encrypted_token="cipher-b",
                        status=KeyStatus.ACTIVE,
                        blocked_until=None,
                        failure_count=0,
                    )
                    session.add_all([key_one, key_two])
                    await session.commit()

                    provider_snapshot = await materialize_model_route_snapshot(session, "google/flash")
                    queue_snapshot = await materialize_model_route_snapshot(session, "queue/prod")

                    materializer = get_route_materializer()
                    invalidate_materialized_route_snapshot("google/flash")
                    invalidate_materialized_route_snapshot("queue/prod")
                    materializer.set_snapshot("google/flash", provider_snapshot)
                    materializer.set_snapshot("queue/prod", queue_snapshot)

                    cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
                    apply_materialized_route_unavailability(
                        provider="google",
                        model_name="flash",
                        provider_key_id=key_one.id,
                        reason="cooldown",
                        cooldown_until=cooldown_until,
                    )

                    patched_provider_snapshot = await ensure_materialized_route_snapshot(session, "google/flash")
                    patched_queue_snapshot = await ensure_materialized_route_snapshot(session, "queue/prod")

                self.assertEqual(
                    [route.provider_key_name for route in patched_provider_snapshot.routes],
                    ["Key B"],
                )
                self.assertEqual(
                    [route.provider_key_name for route in patched_queue_snapshot.routes],
                    ["Key B"],
                )
                self.assertEqual(patched_provider_snapshot.summary.cooldown_count, 1)
                self.assertEqual(patched_queue_snapshot.summary.cooldown_count, 1)
            finally:
                invalidate_materialized_route_snapshot("google/flash")
                invalidate_materialized_route_snapshot("queue/prod")
                await engine.dispose()

    async def _run_alias_materialization_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route-materializer-alias.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            try:
                async with session_factory() as session:
                    queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                    session.add(queue)
                    await session.flush()
                    session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="gemini-3.1-flash", position=0))
                    await session.flush()

                    key = ProviderKey(
                        name="Key Alias",
                        description=None,
                        provider="google",
                        encrypted_token="cipher-a",
                        status=KeyStatus.ACTIVE,
                        blocked_until=None,
                        failure_count=0,
                    )
                    session.add(key)
                    await session.commit()

                    queue_snapshot = await materialize_model_route_snapshot(session, "queue/prod")

                self.assertEqual([route.route for route in queue_snapshot.routes], ["google/gemini-3-flash-preview"])
            finally:
                invalidate_materialized_route_snapshot("queue/prod")
                await engine.dispose()


if __name__ == "__main__":
    unittest.main()
