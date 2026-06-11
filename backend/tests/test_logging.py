from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.core.logging import setup_logging


class LoggingSetupTest(unittest.TestCase):
    def test_setup_logging_writes_to_rotating_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "backend.log"
            settings = Settings(
                log_file_enabled=True,
                log_level="DEBUG",
                log_file_path=str(log_path),
                logging_control_key="debug-key",
            )

            setup_logging(settings)

            logger = logging.getLogger("backend.tests.logging")
            logger.info("hello from logging test")
            logger.debug("debug line")

            for handler in logging.getLogger().handlers:
                flush = getattr(handler, "flush", None)
                if callable(flush):
                    flush()

            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("hello from logging test", content)
            self.assertIn("debug line", content)

    def test_setup_logging_can_run_without_file_logging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "backend.log"
            settings = Settings(
                log_file_enabled=False,
                log_level="INFO",
                log_file_path=str(log_path),
            )

            setup_logging(settings)

            logger = logging.getLogger("backend.tests.logging.no_file")
            logger.info("console only")

            self.assertFalse(log_path.exists())


if __name__ == "__main__":
    unittest.main()
