import unittest

from backend.app.services.cors import build_local_frontend_origins


class CorsConfigTest(unittest.TestCase):
    def test_build_local_frontend_origins_includes_common_local_hosts(self) -> None:
        origins = build_local_frontend_origins(frontend_host="127.0.0.1", frontend_port=4173)

        self.assertEqual(
            origins,
            [
                "http://127.0.0.1:4173",
                "http://[::1]:4173",
                "http://localhost:4173",
            ],
        )

    def test_build_local_frontend_origins_keeps_custom_host(self) -> None:
        origins = build_local_frontend_origins(frontend_host="my-host.local", frontend_port=4173)

        self.assertIn("http://my-host.local:4173", origins)
        self.assertIn("http://localhost:4173", origins)


if __name__ == "__main__":
    unittest.main()
