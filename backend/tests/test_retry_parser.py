import unittest
from datetime import datetime, timezone

import httpx

from backend.app.services.retry_parser import parse_retry_after_seconds, parse_retry_cooldown


class RetryParserTest(unittest.TestCase):
    def test_google_retry_message_reads_milliseconds(self) -> None:
        now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
        result = parse_retry_cooldown(
            httpx.Headers(),
            body={"error": {"message": "Rate limit reached. Please retry in 393.337641ms."}},
            provider="google",
            now=now,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result.retry_after_seconds, 0.393337641)
        self.assertEqual(result.cooldown_until, datetime(2026, 6, 11, 12, 0, 0, 393338, tzinfo=timezone.utc))
        self.assertEqual(result.source, "google-retry-message")

    def test_google_retry_message_reads_seconds(self) -> None:
        now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
        result = parse_retry_cooldown(
            httpx.Headers(),
            body=[{"error": {"message": "Please retry in 1.364102686s"}}],
            provider="google",
            now=now,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result.retry_after_seconds, 1.364102686)
        self.assertEqual(result.cooldown_until, datetime(2026, 6, 11, 12, 0, 1, 364103, tzinfo=timezone.utc))

    def test_google_retry_message_rounds_up_retry_after_seconds(self) -> None:
        seconds = parse_retry_after_seconds(
            httpx.Headers(),
            body="Please retry in 393.337641ms",
            provider="google",
            now=datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(seconds, 1)

    def test_header_parser_takes_precedence_over_body(self) -> None:
        now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
        result = parse_retry_cooldown(
            httpx.Headers({"retry-after": "12"}),
            body="Please retry in 54.895152423s",
            provider="google",
            now=now,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.retry_after_seconds, 12.0)
        self.assertEqual(result.cooldown_until, datetime(2026, 6, 11, 12, 0, 12, tzinfo=timezone.utc))
        self.assertEqual(result.source, "retry-after")


if __name__ == "__main__":
    unittest.main()
