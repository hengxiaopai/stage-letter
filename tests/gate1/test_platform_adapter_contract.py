from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.platforms import (
    CreatorProfileSnapshot,
    LivePlatformAdapter,
    LiveSnapshot,
    ResolvedCreator,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms import AdapterNotFoundError, AdapterRegistry


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "stage_letter" / "application" / "platforms.py"
REGISTRY = ROOT / "stage_letter" / "infrastructure" / "platforms" / "registry.py"


class _Adapter:
    async def resolve_creator(self, input: str) -> ResolvedCreator:
        return ResolvedCreator(platform="demo", platform_user_id=input)

    async def get_creator_profile(self, account: PlatformAccount) -> CreatorProfileSnapshot:
        return CreatorProfileSnapshot(
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            observed_at=datetime.now(timezone.utc),
        )

    async def get_live_snapshot(self, account: PlatformAccount) -> LiveSnapshot:
        return LiveSnapshot(
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            status=LiveStatus.UNKNOWN,
            observed_at=datetime.now(timezone.utc),
            source="demo",
        )


class PlatformAdapterContractTests(unittest.TestCase):
    def test_formal_live_status_is_exactly_three_state(self) -> None:
        self.assertEqual({"LIVE", "OFFLINE", "UNKNOWN"}, {item.value for item in LiveStatus})

    def test_resolved_creator_contains_provider_identity_not_internal_ids(self) -> None:
        resolved = ResolvedCreator(platform="douyin", platform_user_id="123")
        self.assertEqual("douyin", resolved.platform)
        self.assertEqual("123", resolved.platform_user_id)
        self.assertFalse(hasattr(resolved, "creator_id"))
        self.assertFalse(hasattr(resolved, "account_id"))

    def test_live_snapshot_preserves_unknown(self) -> None:
        snapshot = LiveSnapshot(
            platform="douyin",
            platform_user_id="123",
            status=LiveStatus.UNKNOWN,
            observed_at=datetime.now(timezone.utc),
            source="test",
        )
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    def test_contract_is_runtime_structural(self) -> None:
        self.assertIsInstance(_Adapter(), LivePlatformAdapter)

    def test_registry_round_trip(self) -> None:
        registry = AdapterRegistry()
        adapter = _Adapter()
        registry.register("demo", adapter)
        self.assertIs(adapter, registry.get("demo"))
        self.assertTrue(registry.contains("demo"))
        self.assertEqual(("demo",), registry.platforms())

    def test_registry_rejects_duplicate_platform(self) -> None:
        registry = AdapterRegistry()
        registry.register("demo", _Adapter())
        with self.assertRaises(ValueError):
            registry.register("demo", _Adapter())

    def test_registry_rejects_non_adapter(self) -> None:
        registry = AdapterRegistry()
        with self.assertRaises(TypeError):
            registry.register("demo", object())  # type: ignore[arg-type]

    def test_registry_unknown_platform_is_explicit(self) -> None:
        registry = AdapterRegistry()
        with self.assertRaises(AdapterNotFoundError):
            registry.get("missing")

    def test_application_adapter_contract_has_no_infrastructure_or_provider_imports(self) -> None:
        tree = ast.parse(CONTRACT.read_text(encoding="utf-8"), filename=str(CONTRACT))
        forbidden = (
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "fastapi",
            "requests",
            "httpx",
        )
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

    def test_registry_does_not_import_legacy_adapters_or_domain_rules(self) -> None:
        source = REGISTRY.read_text(encoding="utf-8")
        self.assertNotIn("platform_adapters", source)
        self.assertNotIn("core.", source)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("OFFLINE", source)


if __name__ == "__main__":
    unittest.main()
