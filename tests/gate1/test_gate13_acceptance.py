from __future__ import annotations

import ast
import unittest
from pathlib import Path

import stage_letter.infrastructure.platforms as platform_public
from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.bilibili import (
    BILIBILI_LIVE_VALUES,
    BILIBILI_OFFLINE_VALUES,
)
from stage_letter.infrastructure.platforms.bilibili_http import _uid_live_status
from stage_letter.infrastructure.platforms.douyin import (
    DOUYIN_LIVE_VALUES,
    DOUYIN_OFFLINE_VALUES,
)
from stage_letter.infrastructure.platforms.douyu import (
    DOUYU_LIVE_VALUES,
    DOUYU_OFFLINE_VALUES,
)
from stage_letter.infrastructure.platforms.douyu_http import DouyuHttpGateway
from stage_letter.infrastructure.platforms.factory import (
    FORMAL_PLATFORMS,
    build_formal_adapter_registry,
)
from stage_letter.infrastructure.platforms.failures import ProviderOperationError
from stage_letter.infrastructure.platforms.huya import (
    HUYA_LIVE_VALUES,
    HUYA_OFFLINE_VALUES,
)
from stage_letter.infrastructure.platforms.huya_http import HuyaHttpGateway


ROOT = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = ROOT / "stage_letter" / "infrastructure" / "platforms"
FORMAL_RUNTIME_FILES = (
    "bilibili.py",
    "bilibili_http.py",
    "douyin.py",
    "douyin_streamget.py",
    "douyu.py",
    "douyu_http.py",
    "huya.py",
    "huya_http.py",
    "registry.py",
    "factory.py",
)


class Gate13AcceptanceTests(unittest.TestCase):
    def test_live_status_remains_exactly_three_state(self) -> None:
        self.assertEqual({"LIVE", "OFFLINE", "UNKNOWN"}, {item.value for item in LiveStatus})

    def test_formal_platform_set_is_exactly_four(self) -> None:
        self.assertEqual(("bilibili", "douyin", "douyu", "huya"), tuple(sorted(FORMAL_PLATFORMS)))

    def test_public_surface_exposes_all_formal_adapters_gateways_and_factory(self) -> None:
        expected = {
            "BilibiliFormalAdapter",
            "BilibiliHttpGateway",
            "DouyinFormalAdapter",
            "StreamGetDouyinGateway",
            "DouyuFormalAdapter",
            "DouyuHttpGateway",
            "HuyaFormalAdapter",
            "HuyaHttpGateway",
            "AdapterRegistry",
            "AdapterNotFoundError",
            "FORMAL_PLATFORMS",
            "build_formal_adapter_registry",
        }
        self.assertTrue(expected.issubset(set(platform_public.__all__)))
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(platform_public, name))

    def test_evidence_backed_mapping_tables_are_frozen(self) -> None:
        self.assertEqual(frozenset({2}), DOUYIN_LIVE_VALUES)
        self.assertEqual(frozenset({4}), DOUYIN_OFFLINE_VALUES)
        self.assertEqual(frozenset({1}), BILIBILI_LIVE_VALUES)
        self.assertEqual(frozenset({0, 2}), BILIBILI_OFFLINE_VALUES)
        self.assertEqual(frozenset({2, "liveStatus-on"}), HUYA_LIVE_VALUES)
        self.assertEqual(frozenset({1, "liveStatus-off"}), HUYA_OFFLINE_VALUES)
        self.assertEqual(frozenset({1}), DOUYU_LIVE_VALUES)
        self.assertEqual(frozenset({2}), DOUYU_OFFLINE_VALUES)

    def test_each_platform_live_and_offline_mapping_sets_are_disjoint(self) -> None:
        pairs = (
            (DOUYIN_LIVE_VALUES, DOUYIN_OFFLINE_VALUES),
            (BILIBILI_LIVE_VALUES, BILIBILI_OFFLINE_VALUES),
            (HUYA_LIVE_VALUES, HUYA_OFFLINE_VALUES),
            (DOUYU_LIVE_VALUES, DOUYU_OFFLINE_VALUES),
        )
        for live_values, offline_values in pairs:
            with self.subTest(live=live_values, offline=offline_values):
                self.assertTrue(live_values.isdisjoint(offline_values))

    def test_registry_entries_match_platform_keys_and_formal_contract(self) -> None:
        registry = build_formal_adapter_registry()
        self.assertEqual(("bilibili", "douyin", "douyu", "huya"), registry.platforms())
        for platform in registry.platforms():
            adapter = registry.get(platform)
            with self.subTest(platform=platform):
                self.assertIsInstance(adapter, LivePlatformAdapter)
                self.assertEqual(platform, getattr(adapter, "platform"))

    def test_factory_has_no_provider_io_or_cross_layer_business_ownership(self) -> None:
        path = PLATFORM_ROOT / "factory.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, ast.Await)
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden_provider_imports = ("streamget", "httpx", "requests")
        for module in imported:
            self.assertFalse(any(module == item or module.startswith(item + ".") for item in forbidden_provider_imports))
        for token in ("LiveSession", "LiveEvent", "NotificationDelivery", "commit("):
            self.assertNotIn(token, source)

    def test_formal_platform_runtime_has_no_legacy_imports(self) -> None:
        forbidden = ("platform_adapters", "experiments", "core", "api", "workers")
        violations: list[str] = []
        for filename in FORMAL_RUNTIME_FILES:
            path = PLATFORM_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                for module in modules:
                    if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                        violations.append(f"{filename}:{node.lineno}:{module}")
        self.assertEqual([], violations)

    def test_replay_or_loop_signals_do_not_promote_creator_live_truth(self) -> None:
        self.assertEqual(0, _uid_live_status({"liveStatus": 0, "roundStatus": 1}))
        with self.assertRaises(ProviderOperationError):
            DouyuHttpGateway._raw_live_status('<html>{"videoLoop":1}</html>')

    def test_conflicting_or_unsupported_provider_evidence_stays_non_decisive(self) -> None:
        with self.assertRaises(ProviderOperationError):
            HuyaHttpGateway._raw_live_status(
                '<body class="liveStatus-on">{"eLiveStatus":1}</body>'
            )
        with self.assertRaises(ProviderOperationError):
            DouyuHttpGateway._raw_live_status(
                '<html>{"show_status":1,"showStatus":2}</html>'
            )


if __name__ == "__main__":
    unittest.main()
