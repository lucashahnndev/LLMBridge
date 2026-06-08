import unittest

from backend.app.services.tokens import generate_app_token, mask_secret


class TokenHelpersTest(unittest.TestCase):
    def test_generate_app_token_uses_prefix(self) -> None:
        token = generate_app_token()
        self.assertTrue(token.startswith("lk-key-"))
        self.assertGreater(len(token), len("lk-key-"))

    def test_mask_secret_short_values_are_left_as_is(self) -> None:
        self.assertEqual(mask_secret("abc"), "abc")

    def test_mask_secret_hides_middle_section(self) -> None:
        self.assertEqual(mask_secret("1234567890123456"), "123456...3456")


if __name__ == "__main__":
    unittest.main()
