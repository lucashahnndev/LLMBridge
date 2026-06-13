import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.services.auth import (
    is_admin_setup_required,
    set_admin_password,
    verify_admin_login_password,
)


class AdminPasswordFlowTest(unittest.TestCase):
    def test_admin_password_setup_and_override_flow(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_async_engine(f"sqlite+aiosqlite:///{temp_dir}/auth.sqlite")
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            await self._create_schema(engine)

            async with session_factory() as session:
                with patch(
                    "backend.app.services.auth.get_settings",
                    return_value=SimpleNamespace(
                        secret_key="secret",
                        admin_token_ttl_minutes=60,
                        jwt_algorithm="HS256",
                        admin_password="",
                    ),
                ):
                    self.assertTrue(await is_admin_setup_required(session))
                    await set_admin_password(session, "local-password")
                    self.assertFalse(await is_admin_setup_required(session))
                    self.assertTrue(await verify_admin_login_password(session, "local-password"))
                    self.assertFalse(await verify_admin_login_password(session, "wrong-password"))

                with patch(
                    "backend.app.services.auth.get_settings",
                    return_value=SimpleNamespace(
                        secret_key="secret",
                        admin_token_ttl_minutes=60,
                        jwt_algorithm="HS256",
                        admin_password="override-password",
                    ),
                ):
                    self.assertTrue(await verify_admin_login_password(session, "override-password"))

            await engine.dispose()

    async def _create_schema(self, engine) -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    unittest.main()
