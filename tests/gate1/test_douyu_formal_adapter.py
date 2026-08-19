from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.douyu import (
    DouyuFormalAdapter,
    DouyuIdentityRecord,
    DouyuLiveRecord,
    DouyuProfileRecord,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "douyu.py"
NOW = datetime(2026, 8, 19, 7, 0, tzinfo=timezone.utc)
STARTED = datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="501",
        creator_id="601",
        platform="douyu",
        platform_user_id="9999",
        room_id="9999",
        canonical_url="https://www.douyu.com/9999",
    )


class _Gateway:
    def __init__(self) -> None:
        self.identity = DouyuIdentityRecord(
            room_id="9999",
            display_name="Creator",
            canonical_url="https://www.douyu.com/9999",
        )
        self.profile = DouyuProfileRecord(
            room_id="9999",
            observed_at=NOW,
            display_name="Creator",
        )
        self.live = DouyuLiveRecord(
            room_id="9999",
            observed_at=NOW,
            raw_live_status=1,
            source="douyu.desktop_html",
            title="Live title",
            source_started_at=STARTED,
        )
        self.live_error: BaseException | None = None

    async def resolve_identity(self, input: str) -> DouyuIdentityRecord:
        return self.identity

    async def fetch_profile(self, room_id: str) -> DouyuProfileRecord:
        return self.profile

    async def fetch_live(self, room_id: str) -> DouyuLiveRecord:
        if self.live_error is not None:
            raise self.live_error
        return self.live


class DouyuFormalAdapterContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[DouyuFormalAdapter, _Gateway]:
        gateway = _Gateway()
        return DouyuFormalAdapter(gateway), gateway

    async def test_adapter_structurally_implements_formal_contract(self) -> None:
        adapter, _ = self._build()
        self.assertIsInstance(adapter, LivePlatformAdapter)

    async def test_resolve_creator_uses_room_id_without_fabricated_uid(self) -> None:
        adapter, _ = self._build()
        resolved = await adapter.resolve_creator("https://www.douyu.com/9999")
        self.assertEqual("douyu", resolved.platform)
        self.assertEqual("9999", resolved.platform_user_id)
        self.assertEqual("9999", resolved.room_id)
        self.assertFalse(hasattr(resolved, "creator_id"))

    async def test_profile_requires_matching_room_id(self) -> None:
        adapter, gateway = self._build()
        profile = await adapter.get_creator_profile(_account())
        self.assertEqual("9999", profile.platform_user_id)
        gateway.profile = DouyuProfileRecord(room_id="1000", observed_at=NOW)
        with self.assertRaises(ProviderOperationError):
            await adapter.get_creator_profile(_account())

    async def test_show_status_1_maps_to_live(self) -> None:
        adapter, _ = self._build()
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.LIVE, snapshot.status)
        self.assertEqual(STARTED, snapshot.source_started_at)

    async def test_show_status_2_maps_to_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live = DouyuLiveRecord(
            room_id="9999",
            observed_at=NOW,
            raw_live_status=2,
            source="douyu.desktop_html",
            title="stale title",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.OFFLINE, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)

    async def test_ambiguous_or_type_drift_values_stay_unknown(self) -> None:
        adapter, gateway = self._build()
        for raw in (None, 0, 3, 4, -1, "1", "2", True, False, "videoLoop=1"):
            with self.subTest(raw=raw):
                gateway.live = DouyuLiveRecord(
                    room_id="9999",
                    observed_at=NOW,
                    raw_live_status=raw,
                    source="douyu.desktop_html",
                    source_started_at=STARTED,
                )
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
                self.assertIsNone(snapshot.source_started_at)

    async def test_provider_failure_maps_to_unknown_not_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live_error = ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.RATE_LIMITED,
                source="douyu.desktop_html",
            )
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    async def test_timeout_and_network_failure_map_to_unknown(self) -> None:
        for error in (TimeoutError("timeout"), ConnectionError("network")):
            with self.subTest(error=type(error).__name__):
                adapter, gateway = self._build()
                gateway.live_error = error
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    async def test_live_identity_mismatch_maps_to_unknown(self) -> None:
        adapter, gateway = self._build()
        gateway.live = DouyuLiveRecord(
            room_id="1000",
            observed_at=NOW,
            raw_live_status=1,
            source="douyu.desktop_html",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)

    def test_formal_douyu_adapter_has_no_legacy_or_state_engine_imports(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(ADAPTER_PATH))
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
        self.assertNotIn("commit(", source)


if __name__ == "__main__":
    unittest.main()
