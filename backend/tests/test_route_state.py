import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import KeyStatus, ProviderKey
from backend.app.services.availability import (
    apply_route_block,
    apply_route_cooldown,
    get_or_create_provider_key_route_state,
    mark_route_finished,
    mark_route_selected,
    route_state_is_eligible,
)


class ProviderKeyRouteStateTest(unittest.TestCase):
    def test_route_state_tracks_availability_per_model(self) -> None:
        asyncio.run(self._run_state_test())

    async def _run_state_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route-state.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                provider_key = ProviderKey(
                    name="Google A",
                    description=None,
                    provider="google",
                    encrypted_token="cipher",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add(provider_key)
                await session.flush()

                flash_state = await get_or_create_provider_key_route_state(
                    session,
                    provider_key=provider_key,
                    model_name="gemini-3-flash-preview",
                )
                lite_state = await get_or_create_provider_key_route_state(
                    session,
                    provider_key=provider_key,
                    model_name="gemini-3.1-flash-lite",
                )

                apply_route_cooldown(flash_state, delay_seconds=30)
                await session.commit()

                self.assertFalse(route_state_is_eligible(flash_state))
                self.assertTrue(route_state_is_eligible(lite_state))
                self.assertNotEqual(flash_state.model_name, lite_state.model_name)

            await engine.dispose()

    def test_route_state_tracks_in_flight_and_blocking(self) -> None:
        asyncio.run(self._run_runtime_state_test())

    async def _run_runtime_state_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route-state-runtime.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                provider_key = ProviderKey(
                    name="Google B",
                    description=None,
                    provider="google",
                    encrypted_token="cipher",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add(provider_key)
                await session.flush()

                state = await get_or_create_provider_key_route_state(
                    session,
                    provider_key=provider_key,
                    model_name="gemini-2.5-flash",
                )
                now = datetime.now(timezone.utc)
                mark_route_selected(state, now=now, soft_reservation_ms=250, next_available_delay_ms=500)
                self.assertEqual(state.in_flight_count, 1)
                self.assertEqual(state.last_used_at, now)
                self.assertFalse(route_state_is_eligible(state, now=now))

                mark_route_finished(state, now=now + timedelta(milliseconds=250), next_available_delay_ms=700)
                self.assertEqual(state.in_flight_count, 0)
                self.assertIsNone(state.soft_reserved_until)
                self.assertFalse(route_state_is_eligible(state, now=now + timedelta(milliseconds=300)))

                apply_route_block(
                    state,
                    blocked_until=now + timedelta(seconds=60),
                    disabled=True,
                    disabled_reason="unauthorized",
                )
                self.assertTrue(state.disabled)
                self.assertEqual(state.disabled_reason, "unauthorized")
                self.assertFalse(route_state_is_eligible(state, now=now + timedelta(seconds=61)))

            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
