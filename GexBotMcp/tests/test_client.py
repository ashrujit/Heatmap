from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gexbot_mcp.client import GexBotConfig  # noqa: E402


class ClientConfigTests(unittest.TestCase):
    def test_config_loads_local_env_and_masks_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "GEXBOT_API_KEY=test_custom_abcdef123456\n"
                "GEXBOT_API_V2_URL=https://example.test/v2\n",
                encoding="utf-8",
            )

            config = GexBotConfig.from_env(env_path)

        self.assertTrue(config.key_loaded)
        self.assertEqual(config.api_v2_url, "https://example.test/v2")
        self.assertEqual(config.masked_key, "test_custom_a...3456")


if __name__ == "__main__":
    unittest.main()
