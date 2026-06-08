import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.services import runtime as runtime_service


class RuntimeConfigTest(unittest.TestCase):
    def test_update_runtime_config_writes_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / '.env'
            env_path.write_text(
                'SECRET_KEY=abc\nADMIN_PASSWORD=def\nHOST=127.0.0.1\nPORT=8000\n',
                encoding='utf-8',
            )

            fake_settings = SimpleNamespace(host='127.0.0.1', port=8000)
            with patch.object(runtime_service, 'ENV_FILE', env_path), patch.object(
                runtime_service,
                'get_settings',
                return_value=fake_settings,
            ):
                result = runtime_service.update_runtime_config(host='127.0.0.1', port=9001)

            written = env_path.read_text(encoding='utf-8')
            self.assertIn('HOST=127.0.0.1', written)
            self.assertIn('PORT=9001', written)
            self.assertEqual(result.port, 9001)
            self.assertEqual(result.api_base_url, 'http://127.0.0.1:9001/api/v1')


if __name__ == '__main__':
    unittest.main()
