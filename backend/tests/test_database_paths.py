import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.database.session import _ensure_sqlite_database_parent
from scripts import bootstrap_env


class DatabasePathTest(unittest.TestCase):
    def test_bootstrap_env_defaults_database_url_to_backend_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "backend" / ".env"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text("SECRET_KEY=abc\nADMIN_PASSWORD=xyz\n", encoding="utf-8")

            with patch.object(bootstrap_env, "ENV_PATH", env_path):
                self.assertEqual(bootstrap_env.main(), 0)

            rendered = env_path.read_text(encoding="utf-8")
            self.assertIn("DATABASE_URL=sqlite+aiosqlite:///./backend/data/database.db", rendered)

    def test_bootstrap_env_rewrites_legacy_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "backend" / ".env"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(
                "\n".join(
                    [
                        "SECRET_KEY=abc",
                        "ADMIN_PASSWORD=xyz",
                        "DATABASE_URL=sqlite+aiosqlite:///./backend/database.db",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(bootstrap_env, "ENV_PATH", env_path):
                self.assertEqual(bootstrap_env.main(), 0)

            rendered = env_path.read_text(encoding="utf-8")
            self.assertIn("DATABASE_URL=sqlite+aiosqlite:///./backend/data/database.db", rendered)
            self.assertNotIn("backend/database.db", rendered)

    def test_sqlite_database_parent_is_created_before_engine_boot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nested" / "backend" / "data" / "database.db"
            _ensure_sqlite_database_parent(f"sqlite+aiosqlite:///{db_path}")

            self.assertTrue(db_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
