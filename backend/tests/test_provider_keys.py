import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import KeyStatus, ProviderKey, ProviderKeyRouteState
from backend.app.routes.provider_keys import reset_provider_key_runtime_state
from backend.app.services.crypto import decrypt_text, encrypt_text


class ProviderKeyRuntimeResetTest(unittest.TestCase):
    def test_reset_provider_key_runtime_state_reactivates_key_and_clears_route_states(self) -> None:
        asyncio.run(self._run_reset_test())

    async def _run_reset_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "provider-keys.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                provider_key = ProviderKey(
                    name="GitHub primary",
                    description=None,
                    provider="github",
                    encrypted_token=encrypt_text("old-token"),
                    status=KeyStatus.INVALID,
                    blocked_until=None,
                    failure_count=3,
                )
                session.add(provider_key)
                await session.flush()
                session.add(
                    ProviderKeyRouteState(
                        provider_key_id=provider_key.id,
                        provider="github",
                        model_name="openai/gpt-4.1",
                        disabled=True,
                        disabled_reason="unauthorized",
                    )
                )
                await session.commit()

                provider_key.encrypted_token = encrypt_text("new-token")
                await reset_provider_key_runtime_state(session, provider_key)
                await session.commit()

                refreshed_key = await session.get(ProviderKey, provider_key.id)
                self.assertIsNotNone(refreshed_key)
                if refreshed_key is not None:
                    self.assertEqual(refreshed_key.status, KeyStatus.ACTIVE)
                    self.assertEqual(refreshed_key.failure_count, 0)
                    self.assertIsNone(refreshed_key.blocked_until)
                    self.assertEqual(decrypt_text(refreshed_key.encrypted_token), "new-token")

                route_states = await session.execute(
                    select(ProviderKeyRouteState).where(ProviderKeyRouteState.provider_key_id == provider_key.id)
                )
                self.assertEqual(route_states.scalars().all(), [])

            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
