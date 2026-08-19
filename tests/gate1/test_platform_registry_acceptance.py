from __future__ import annotations

import ast
import builtins
import unittest
from pathlib import Path
from unittest.mock import patch

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.infrastructure.platforms.bilibili import BilibiliFormalAdapter
from stage_letter.infrastructure.platforms.douyin import DouyinFormalAdapter
from stage_letter.infrastructure.platforms.douyu import DouyuFormalAdapter
from stage_letter.infrastructure.platforms.factory import (
    FORMAL_PLATFORMS,
    build_formal_adapter_registry,
)
from stage_letter.infrastructure.platforms.huya import HuyaFormalAdapter
from stage_letter.infrastructure.platforms.registry import AdapterNotFoundError


ROOT = Path(__file__).resolve().parents[2]
FACTORY_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "factory.py"


class PlatformRegistryAcceptanceTests(unittest.TestCase):
    def test_default_registry_contains_exact_formal_platforms(self) -> None:
        registry = build_formal_adapter_registry()
        self.assertEqual(tuple(sorted(FORMAL_PLATFORMS)), registry.platforms())
        self.assertEqual(("bilibili", "douyin", "douyu", "huya"), registry.platforms())

    def test_all_registered_entries_implement_formal_contract(self) -> None:
        registry = build_formal_adapter_registry()
        for platform in registry.platforms():
            with self.subTest(platform=platform):
                self.assertIsInstance(registry.get(platform), LivePlatformAdapter)

    def test_registered_adapter_platform_attribute_matches_registry_key(self) -> None:
        registry = build_formal_adapter_registry()
        for platform in registry.platforms():
            with self.subTest(platform=platform):
                self.assertEqual(platform, getattr(registry.get(platform), "platform"))

    def test_registry_uses_only_formal_concrete_adapter_types(self) -> None:
        registry = build_formal_adapter_registry()
        expected = {
            "douyin": DouyinFormalAdapter,
            "bilibili": BilibiliFormalAdapter,
            "huya": HuyaFormalAdapter,
            "douyu": DouyuFormalAdapter,
        }
        for platform, adapter_type in expected.items():
            with self.subTest(platform=platform):
                self.assertIsInstance(registry.get(platform), adapter_type)

    def test_build_does_not_require_eager_streamget_import(self) -> None:
        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamget" or name.startswith("streamget."):
                raise AssertionError("registry construction must not import streamget eagerly")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guarded_import):
            registry = build_formal_adapter_registry()
        self.assertTrue(registry.contains("douyin"))

    def test_each_build_returns_fresh_registry_and_adapter_instances(self) -> None:
        first = build_formal_adapter_registry()
        second = build_formal_adapter_registry()
        self.assertIsNot(first, second)
        for platform in first.platforms():
            with self.subTest(platform=platform):
                self.assertIsNot(first.get(platform), second.get(platform))

    def test_unknown_platform_remains_explicit(self) -> None:
        registry = build_formal_adapter_registry()
        with self.assertRaises(AdapterNotFoundError):
            registry.get("missing")

    def test_factory_has_no_legacy_or_state_engine_dependency(self) -> None:
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        forbidden = ("platform_adapters", "experiments", "core", "api", "workers")
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("Notification", source)
        self.assertNotIn("commit(", source)


if __name__ == "__main__":
    unittest.main()
