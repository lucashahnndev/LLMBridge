import unittest

from backend.app.services.alerts import (
    format_provider_pool_exhausted_alert,
    format_proxy_failure_alert,
    format_queue_exhausted_alert,
)


class TelegramAlertFormattingTest(unittest.TestCase):
    def test_format_proxy_failure_alert_includes_core_context(self) -> None:
        message = format_proxy_failure_alert(
            app_token_name="Atlas",
            requested_model="queue/gemini",
            final_route="google/gemini-3-flash-preview",
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

        self.assertIn("Proxy failure", message)
        self.assertIn("App token: Atlas", message)
        self.assertIn("Queue: gemini", message)
        self.assertIn("Final route: google/gemini-3-flash-preview", message)
        self.assertIn("Tool calling: yes", message)
        self.assertIn("Error: Provider timeout", message)

    def test_format_queue_exhausted_alert_is_direct(self) -> None:
        message = format_queue_exhausted_alert(
            app_token_name="Atlas",
            queue_name="gemini",
            requested_model="queue/gemini",
            protocol_in="openai",
            protocol_out="openai",
            error="Queue 'gemini' has no active candidates",
        )

        self.assertIn("Queue exhausted", message)
        self.assertIn("Queue: gemini", message)
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

        self.assertIn("Provider pool exhausted", message)
        self.assertIn("Provider: google", message)
        self.assertIn("No eligible provider keys available for provider 'google'", message)


if __name__ == "__main__":
    unittest.main()
