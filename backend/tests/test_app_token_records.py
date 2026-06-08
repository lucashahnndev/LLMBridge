import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.services.records import app_token_create_response, app_token_response


class AppTokenRecordHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app_token = SimpleNamespace(
            id=1,
            name='Atlas',
            environment=SimpleNamespace(value='development'),
            is_active=True,
            rpm_limit=None,
            created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
            token='lk-key-abcdefghijklmnopqrstuvwxyz123456',
        )

    def test_app_token_response_masks_token(self) -> None:
        response = app_token_response(self.app_token)
        self.assertEqual(response.masked_token, 'lk-key...3456')
        self.assertNotEqual(response.masked_token, self.app_token.token)

    def test_app_token_create_response_includes_raw_token(self) -> None:
        response = app_token_create_response(self.app_token, self.app_token.token)
        self.assertEqual(response.token, self.app_token.token)
        self.assertEqual(response.masked_token, 'lk-key...3456')


if __name__ == '__main__':
    unittest.main()
