import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.services import telegram_bot


class TelegramBotCommandTest(unittest.TestCase):
    def test_parse_telegram_command_supports_bot_mentions(self) -> None:
        command, args = telegram_bot.parse_telegram_command("/alerts@LLMBridgeBot proxy off")

        self.assertEqual(command, "alerts")
        self.assertEqual(args, ["proxy", "off"])

    def test_help_lists_app_and_provider_commands(self) -> None:
        message = telegram_bot.build_help_message()

        self.assertIn("/apps - app token summary", message)
        self.assertIn("/providers - provider summary", message)
        self.assertIn("/queues - queue summary", message)

    def test_execute_link_command_binds_chat_and_enables_telegram(self) -> None:
        asyncio.run(self._run_link())

    async def _run_link(self) -> None:
        worker = telegram_bot.TelegramBotWorker(sessionmaker=SimpleNamespace())
        fake_settings = SimpleNamespace(telegram_enabled=True, telegram_chat_id="123", alert_proxy_failures=True,
                                        alert_queue_exhausted=True, alert_provider_pool_exhausted=True,
                                        alert_provider_key_status_changes=True)

        with patch.object(telegram_bot, "read_runtime_config", return_value=SimpleNamespace(
            host="127.0.0.1", port=8009, api_base_url="http://127.0.0.1:8009/api/v1", restart_required=False
        )), patch.object(telegram_bot, "update_alert_settings", new=AsyncMock(return_value=fake_settings)) as update_mock:
            response = await worker._execute_command(
                session=object(),
                chat_id="123",
                command="link",
                args=[],
            )

        self.assertIn("Telegram chat linked.", response or "")
        update_mock.assert_awaited_once()
        _, kwargs = update_mock.await_args
        self.assertEqual(kwargs["telegram_chat_id"], "123")
        self.assertTrue(kwargs["telegram_enabled"])

    def test_execute_alerts_toggle_updates_only_requested_flag(self) -> None:
        asyncio.run(self._run_alerts_toggle())

    def test_execute_apps_command_returns_summary(self) -> None:
        asyncio.run(self._run_apps())

    def test_execute_providers_command_returns_summary(self) -> None:
        asyncio.run(self._run_providers())

    async def _run_alerts_toggle(self) -> None:
        worker = telegram_bot.TelegramBotWorker(sessionmaker=SimpleNamespace())
        fake_settings = SimpleNamespace(
            telegram_enabled=True,
            telegram_chat_id="123",
            alert_proxy_failures=False,
            alert_queue_exhausted=True,
            alert_provider_pool_exhausted=False,
            alert_provider_key_status_changes=True,
        )

        with patch.object(telegram_bot, "read_runtime_config", return_value=SimpleNamespace(
            host="127.0.0.1", port=8009, api_base_url="http://127.0.0.1:8009/api/v1", restart_required=False
        )), patch.object(telegram_bot, "update_alert_settings", new=AsyncMock(return_value=fake_settings)) as update_mock:
            response = await worker._execute_command(
                session=object(),
                chat_id="123",
                command="alerts",
                args=["provider", "off"],
            )

        self.assertIn("Provider pool: off", response or "")
        update_mock.assert_awaited_once()
        _, kwargs = update_mock.await_args
        self.assertEqual(kwargs["alert_provider_pool_exhausted"], False)

    async def _run_apps(self) -> None:
        worker = telegram_bot.TelegramBotWorker(sessionmaker=SimpleNamespace())
        class _Row:
            name = "Atlas"
            environment = SimpleNamespace(value="development")
            is_active = True
            requests_count = 12
            total_tokens_consumed = 345
            avg_latency_ms = 12.3

        fake_session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [_Row()])))
        response = await worker._execute_command(
            session=fake_session,
            chat_id="123",
            command="apps",
            args=[],
        )

        self.assertIn("App tokens", response or "")
        self.assertIn("Atlas", response or "")
        self.assertIn("12 req", response or "")

    async def _run_providers(self) -> None:
        worker = telegram_bot.TelegramBotWorker(sessionmaker=SimpleNamespace())

        class _Result:
            def all(self):
                return [("google", 2), ("openai", 1)]

        fake_session = SimpleNamespace(execute=AsyncMock(return_value=_Result()))
        with patch.object(telegram_bot, "_provider_request_counts", new=AsyncMock(return_value={"google": 9, "openai": 2})):
            response = await worker._execute_command(
                session=fake_session,
                chat_id="123",
                command="providers",
                args=[],
            )

        self.assertIn("Providers", response or "")
        self.assertIn("google", response or "")
        self.assertIn("2 keys", response or "")


if __name__ == "__main__":
    unittest.main()
