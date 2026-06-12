import unittest
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

from backend.app.services.proxy import (
    extract_usage_metrics,
    format_provider_pool_exhausted_message,
    parse_model_identifier,
    parse_retry_after_seconds,
)


class ProxyHelperTest(unittest.TestCase):
    def test_parse_model_identifier_splits_provider_and_model(self) -> None:
        provider, model_name = parse_model_identifier("openai/gpt-4o-mini")
        self.assertEqual(provider, "openai")
        self.assertEqual(model_name, "gpt-4o-mini")

    def test_parse_model_identifier_rejects_invalid_format(self) -> None:
        with self.assertRaises(HTTPException):
            parse_model_identifier("gpt-4o-mini")

    def test_extract_usage_metrics_reads_usage_payload(self) -> None:
        prompt_tokens, completion_tokens, total_tokens = extract_usage_metrics(
            {
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                }
            }
        )
        self.assertEqual((prompt_tokens, completion_tokens, total_tokens), (12, 8, 20))

    def test_extract_usage_metrics_defaults_when_usage_missing(self) -> None:
        self.assertEqual(extract_usage_metrics({}), (0, 0, 0))

    def test_format_provider_pool_exhausted_message_reports_cooldown(self) -> None:
        message = format_provider_pool_exhausted_message(
            "google",
            total=3,
            active=0,
            cooldown=3,
            invalid=0,
            next_retry_at=None,
        )
        self.assertIn("No eligible provider keys available", message)
        self.assertIn("total=3", message)

    def test_format_provider_pool_exhausted_message_reports_retry_time(self) -> None:
        from datetime import datetime, timezone

        message = format_provider_pool_exhausted_message(
            "google",
            total=3,
            active=0,
            cooldown=3,
            invalid=0,
            next_retry_at=datetime(2026, 6, 8, 3, 19, 17, tzinfo=timezone.utc),
        )
        self.assertIn("cooling down until", message)
        self.assertIn("2026-06-08T03:19:17+00:00", message)

    def test_parse_retry_after_seconds_reads_numeric_header(self) -> None:
        headers = httpx.Headers({"retry-after": "12"})
        self.assertEqual(parse_retry_after_seconds(headers), 12)

    def test_parse_retry_after_seconds_reads_http_date_header(self) -> None:
        now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
        headers = httpx.Headers({"retry-after": "Thu, 11 Jun 2026 12:00:05 GMT"})
        self.assertEqual(parse_retry_after_seconds(headers, now=now), 5)


if __name__ == "__main__":
    unittest.main()
