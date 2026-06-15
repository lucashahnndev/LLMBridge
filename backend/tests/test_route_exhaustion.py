import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import (
    KeyStatus,
    ModelQueue,
    ModelQueueCandidate,
    ProviderKey,
    ProviderKeyModelCooldown,
    ProviderKeyRouteState,
    QueueStrategy,
)
from backend.app.services.queues import resolve_model_route_snapshot, resolve_model_routes


class RouteExhaustionTest(unittest.TestCase):
    def test_queue_with_eligible_key_returns_routes(self) -> None:
        asyncio.run(self._run_queue_eligible_test())

    def test_queue_all_cooldown_returns_429_with_retry_after(self) -> None:
        asyncio.run(self._run_queue_all_cooldown_test())

    def test_queue_all_disabled_or_blocked_returns_structural_error(self) -> None:
        asyncio.run(self._run_queue_structural_unavailable_test())

    def test_queue_mixed_disabled_and_cooldown_returns_429(self) -> None:
        asyncio.run(self._run_queue_mixed_test())

    def test_direct_route_all_cooldown_returns_429(self) -> None:
        asyncio.run(self._run_direct_all_cooldown_test())

    def test_direct_route_all_disabled_or_blocked_returns_structural_error(self) -> None:
        asyncio.run(self._run_direct_structural_test())

    def test_direct_route_with_eligible_keys_balances_order(self) -> None:
        asyncio.run(self._run_direct_eligible_balance_test())

    def test_direct_route_alias_respects_cooldown_for_resolved_operational_model(self) -> None:
        asyncio.run(self._run_direct_alias_cooldown_test())

    def test_new_route_state_cooldown_is_respected_even_when_legacy_table_is_empty(self) -> None:
        asyncio.run(self._run_new_state_without_legacy_test())

    def test_legacy_cooldown_does_not_override_new_operational_state(self) -> None:
        asyncio.run(self._run_legacy_does_not_override_new_state_test())

    async def _create_session_factory(self, db_name: str):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / db_name
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return temp_dir, engine, session_factory

    async def _run_queue_eligible_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("queue-eligible.sqlite")
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
                await session.commit()

                snapshot = await resolve_model_route_snapshot(session, "queue/prod")

            self.assertEqual(snapshot.summary.eligible_count, 1)
            self.assertEqual(snapshot.summary.cooldown_count, 0)
            self.assertEqual([route.provider_key_name for route in snapshot.routes], ["Key A"])
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_queue_all_cooldown_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("queue-cooldown.sqlite")
        try:
            async with session_factory() as session:
                queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0))
                await session.flush()

                key_a = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="a", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                key_b = ProviderKey(name="Key B", description=None, provider="google", encrypted_token="b", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add_all([key_a, key_b])
                await session.flush()
                now = datetime.now(timezone.utc)
                session.add_all(
                    [
                        ProviderKeyRouteState(provider_key_id=key_a.id, provider="google", model_name="flash", cooldown_until=now + timedelta(seconds=300)),
                        ProviderKeyRouteState(provider_key_id=key_b.id, provider="google", model_name="flash", cooldown_until=now + timedelta(seconds=120)),
                    ]
                )
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "queue/prod")

            self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            retry_after = int(ctx.exception.headers["Retry-After"])
            self.assertGreaterEqual(retry_after, 110)
            self.assertLessEqual(retry_after, 120)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_queue_structural_unavailable_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("queue-structural.sqlite")
        try:
            async with session_factory() as session:
                queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0))
                await session.flush()

                invalid_key = ProviderKey(name="Invalid", description=None, provider="google", encrypted_token="x", status=KeyStatus.INVALID, blocked_until=None, failure_count=0)
                blocked_key = ProviderKey(
                    name="Blocked",
                    description=None,
                    provider="google",
                    encrypted_token="y",
                    status=KeyStatus.ACTIVE,
                    blocked_until=datetime.now(timezone.utc) + timedelta(hours=1),
                    failure_count=0,
                )
                session.add_all([invalid_key, blocked_key])
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "queue/prod")

            self.assertEqual(ctx.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertIsNone(ctx.exception.headers)
            self.assertEqual(ctx.exception.detail["code"], "route_unavailable")
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_queue_mixed_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("queue-mixed.sqlite")
        try:
            async with session_factory() as session:
                queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.ORDERED, is_active=True)
                session.add(queue)
                await session.flush()
                session.add(ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0))
                await session.flush()

                invalid_key = ProviderKey(name="Invalid", description=None, provider="google", encrypted_token="x", status=KeyStatus.INVALID, blocked_until=None, failure_count=0)
                cooldown_key = ProviderKey(name="Cooldown", description=None, provider="google", encrypted_token="y", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add_all([invalid_key, cooldown_key])
                await session.flush()
                session.add(
                    ProviderKeyRouteState(
                        provider_key_id=cooldown_key.id,
                        provider="google",
                        model_name="flash",
                        cooldown_until=datetime.now(timezone.utc) + timedelta(seconds=180),
                    )
                )
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "queue/prod")

            self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            retry_after = int(ctx.exception.headers["Retry-After"])
            self.assertGreaterEqual(retry_after, 170)
            self.assertLessEqual(retry_after, 180)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_direct_all_cooldown_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("direct-cooldown.sqlite")
        try:
            async with session_factory() as session:
                key = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="a", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add(key)
                await session.flush()
                session.add(
                    ProviderKeyRouteState(
                        provider_key_id=key.id,
                        provider="google",
                        model_name="flash",
                        cooldown_until=datetime.now(timezone.utc) + timedelta(seconds=240),
                    )
                )
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "google/flash")

            self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertIn("Retry-After", ctx.exception.headers)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_direct_structural_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("direct-structural.sqlite")
        try:
            async with session_factory() as session:
                key = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="a", status=KeyStatus.SUSPENDED_BILLING, blocked_until=None, failure_count=0)
                session.add(key)
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "google/flash")

            self.assertEqual(ctx.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(ctx.exception.detail["code"], "pool_unavailable")
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_direct_alias_cooldown_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("direct-alias-cooldown.sqlite")
        try:
            async with session_factory() as session:
                key = ProviderKey(
                    name="Key Alias",
                    description=None,
                    provider="google",
                    encrypted_token="a",
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
                        model_name="gemini-3-flash-preview",
                        cooldown_until=datetime.now(timezone.utc) + timedelta(seconds=120),
                    )
                )
                await session.commit()

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "google/gemini-3.1-flash")

            self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertIn("Retry-After", ctx.exception.headers)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_direct_eligible_balance_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("direct-balance.sqlite")
        try:
            async with session_factory() as session:
                key_one = ProviderKey(name="Key One", description=None, provider="google", encrypted_token="a", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                key_two = ProviderKey(name="Key Two", description=None, provider="google", encrypted_token="b", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add_all([key_one, key_two])
                await session.flush()
                now = datetime(2026, 6, 11, 18, 0, 0, tzinfo=timezone.utc)
                session.add_all(
                    [
                        ProviderKeyRouteState(provider_key_id=key_one.id, provider="google", model_name="flash", in_flight_count=1, last_used_at=now - timedelta(seconds=5)),
                        ProviderKeyRouteState(provider_key_id=key_two.id, provider="google", model_name="flash", in_flight_count=0, last_used_at=now - timedelta(seconds=10)),
                    ]
                )
                await session.commit()

                snapshot = await resolve_model_route_snapshot(session, "google/flash")

            self.assertEqual(snapshot.summary.eligible_count, 2)
            self.assertEqual([route.provider_key_name for route in snapshot.routes], ["Key Two", "Key One"])
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_new_state_without_legacy_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("new-state-without-legacy.sqlite")
        try:
            async with session_factory() as session:
                key = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="a", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
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

                legacy_rows = (
                    await session.execute(select(ProviderKeyModelCooldown).where(ProviderKeyModelCooldown.provider_key_id == key.id))
                ).scalars().all()
                self.assertEqual(len(legacy_rows), 0)

                with self.assertRaises(HTTPException) as ctx:
                    await resolve_model_routes(session, "google/flash")

            self.assertEqual(ctx.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_legacy_does_not_override_new_state_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("legacy-does-not-override.sqlite")
        try:
            async with session_factory() as session:
                key = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="a", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add(key)
                await session.flush()
                session.add(
                    ProviderKeyModelCooldown(
                        provider_key_id=key.id,
                        model_name="flash",
                        blocked_until=datetime.now(timezone.utc) + timedelta(seconds=120),
                        failure_count=1,
                    )
                )
                session.add(
                    ProviderKeyRouteState(
                        provider_key_id=key.id,
                        provider="google",
                        model_name="flash",
                        cooldown_until=None,
                    )
                )
                await session.commit()

                snapshot = await resolve_model_route_snapshot(session, "google/flash")

            self.assertEqual(snapshot.summary.eligible_count, 1)
            self.assertEqual([route.provider_key_name for route in snapshot.routes], ["Key A"])
        finally:
            await engine.dispose()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
