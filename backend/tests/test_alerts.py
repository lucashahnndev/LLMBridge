import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.services.alerts import (
    format_provider_pool_exhausted_alert,
    format_proxy_failure_alert,
    format_queue_exhausted_alert,
    send_telegram_test_message,
    _send_telegram_message,
)


class TelegramAlertFormattingTest(unittest.TestCase):
    def test_format_proxy_failure_alert_includes_core_context(self) -> None:
        message = format_proxy_failure_alert(
            app_token_name="Atlas",
            requested_model="queue/gemini",
            final_route="google/gemini-3-flash-preview",
            final_provider_key_name="Key B",
            route_kind="queue",
            queue_name="gemini",
            protocol_in="anthropic",
            protocol_out="openai",
            status_code=502,
            attempts=3,
            tool_calling=True,
            rotated=True,
            error={"error": {"message": "Provider timeout"}},
        )

        self.assertIn("*LLMBridge Proxy failure*", message)
        self.assertIn("```text", message)
        self.assertIn("• *App token:* `Atlas`", message)
        self.assertIn("• *Requested model:* `queue/gemini`", message)
        self.assertIn("• *Final route:* `google/gemini-3-flash-preview`", message)
        self.assertIn("• *Final provider key:* `Key B`", message)
        self.assertIn("• *Tool calling:* `yes`", message)
        self.assertIn("*Error log*", message)
        self.assertIn("Provider timeout", message)

    def test_format_queue_exhausted_alert_is_direct(self) -> None:
        message = format_queue_exhausted_alert(
            app_token_name="Atlas",
            queue_name="gemini",
            requested_model="queue/gemini",
            protocol_in="openai",
            protocol_out="openai",
            error="Queue 'gemini' has no active candidates",
        )

        self.assertIn("*LLMBridge Queue exhausted*", message)
        self.assertIn("```text", message)
        self.assertIn("• *Queue:* `gemini`", message)
        self.assertIn("Queue 'gemini' has no active candidates", message)

    def test_format_provider_pool_exhausted_alert_is_direct(self) -> None:
        message = format_provider_pool_exhausted_alert(
            app_token_name="Atlas",
            provider="google",
            requested_model="google/gemini-3.1-flash",
            protocol_in="openai",
            protocol_out="openai",
            error="No eligible provider keys available for provider 'google'",
        )

        self.assertIn("*LLMBridge Provider pool exhausted*", message)
        self.assertIn("```text", message)
        self.assertIn("• *Provider:* `google`", message)
        self.assertIn("No eligible provider keys available for provider 'google'", message)

    def test_send_telegram_test_message_uses_provided_credentials(self) -> None:
        asyncio_result = self._run_send_telegram_test_message()
        self.assertEqual(asyncio_result, "987654321")

    def test_send_telegram_message_builds_telegram_request(self) -> None:
        asyncio_result = self._run_send_telegram_message()
        self.assertIsNone(asyncio_result)

    def _run_send_telegram_test_message(self) -> str:
        import asyncio

        async def _run() -> str:
            fake_settings = SimpleNamespace(telegram_bot_token="", telegram_chat_id="123")
            fake_alert_settings = SimpleNamespace(
                telegram_bot_token_encrypted=None,
                telegram_chat_id="123",
            )

            with patch("backend.app.services.alerts.get_settings", return_value=fake_settings), patch(
                "backend.app.services.alerts.get_alert_settings", new=AsyncMock(return_value=fake_alert_settings)
            ), patch("backend.app.services.alerts._send_telegram_message", new=AsyncMock()) as send_mock:
                chat_id = await send_telegram_test_message(
                    session=SimpleNamespace(),
                    telegram_bot_token="  test-token  ",
                    telegram_chat_id=" 987654321 ",
                )

            send_mock.assert_awaited_once()
            kwargs = send_mock.await_args.kwargs
            self.assertEqual(kwargs["bot_token"], "test-token")
            self.assertEqual(kwargs["chat_id"], "987654321")
            self.assertEqual(kwargs["parse_mode"], "MarkdownV2")
            self.assertIn("*LLMBridge Telegram test*", kwargs["text"])
            self.assertIn("Telegram delivery is working", kwargs["text"])
            return chat_id

        return asyncio.run(_run())

    def _run_send_telegram_message(self) -> None:
        import asyncio

        async def _run() -> None:
            fake_client = SimpleNamespace()
            fake_client.post = AsyncMock(
                return_value=SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"ok": True, "result": {}},
                )
            )

            class _ClientContext:
                def __init__(self) -> None:
                    self.client = fake_client

                async def __aenter__(self):
                    return self.client

                async def __aexit__(self, exc_type, exc, tb):
                    return None

            with patch("backend.app.services.alerts.httpx.AsyncClient", return_value=_ClientContext()):
                await _send_telegram_message(bot_token="abc", chat_id="123", text="hello")

            fake_client.post.assert_awaited_once()
            args = fake_client.post.await_args.args
            kwargs = fake_client.post.await_args.kwargs
            self.assertIn("/botabc/sendMessage", args[0])
            self.assertEqual(kwargs["json"]["chat_id"], "123")
            self.assertEqual(kwargs["json"]["text"], "hello")
            self.assertNotIn("parse_mode", kwargs["json"])

        return asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
