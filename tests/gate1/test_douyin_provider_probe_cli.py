from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "gate13_douyin_provider_probe.py"

spec = importlib.util.spec_from_file_location("gate13_douyin_provider_probe", PROBE_PATH)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class DouyinProviderProbeCliTests(unittest.TestCase):
    def test_raw_profile_url_is_unchanged(self) -> None:
        value = "https://www.douyin.com/user/sec_uid_abc"
        normalized, changed = probe._normalize_cli_identity(value)
        self.assertEqual(value, normalized)
        self.assertFalse(changed)

    def test_equal_markdown_link_is_safely_unwrapped(self) -> None:
        url = "https://www.douyin.com/user/sec_uid_abc"
        normalized, changed = probe._normalize_cli_identity(f"[{url}]({url})")
        self.assertEqual(url, normalized)
        self.assertTrue(changed)

    def test_mismatched_markdown_link_is_rejected(self) -> None:
        visible = "https://www.douyin.com/user/sec_uid_abc"
        target = "https://www.douyin.com/user/other_identity"
        with self.assertRaises(ValueError):
            probe._normalize_cli_identity(f"[{visible}]({target})")


if __name__ == "__main__":
    unittest.main()
