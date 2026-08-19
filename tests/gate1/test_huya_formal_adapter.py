from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)
from stage_letter.infrastructure.platforms.huya import (
    HuyaFormalAdapter,
    HuyaIdentityRecord,
    HuyaLiveRecord,
    HuyaProfileRecord,
)


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "huya.py"
NOW = datetime(2026, 8, 19, 6, 20, tzinfo=timezone.utc)
STARTED = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="501",
        creator_id="601",
        platform="huya",
        platform_user_id="998",
        room_id="998",
        canonical_url="https://www.huya.com/998",
    )


class _Gateway:
    def __init__(self) -> None:
        self.identity = HuyaIdentityRecord(
            room_id="998",
            canonical_url="https://www.huya.com/998",
        )
        self.profile = HuyaProfileRecord(room_id="998", observed_at=NOW)
        self.live = HuyaLiveRecord(
            room_id="998",
            observed_at=NOW,
            raw_live_status=2,
            source="huya.mobile_html",
            title="Live title",
            source_started_at=STARTED,
        )
        self.live_error: BaseException | None = None

    async def resolve_identity(self, input: str) -> HuyaIdentityRecord:
        return self.identity

    async def fetch_profile(self, room_id: str) -> HuyaProfileRecord:
        return self.profile

    async def fetch_live(self, room_id: str) -> HuyaLiveRecord:
        if self.live_error is not None:
            raise self.live_error
        return self.live


class HuyaFormalAdapterContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[HuyaFormalAdapter, _Gateway]:
        gateway = _Gateway()
        return HuyaFormalAdapter(gateway), gateway

    async def test_adapter_structurally_implements_formal_contract(self) -> None:
        adapter, _ = self._build()
        self.assertIsInstance(adapter, LivePlatformAdapter)

    async def test_resolve_creator_uses_room_id_without_fabricated_creator_uid(self) -> None:
        adapter, _ = self._build()
        resolved = await adapter.resolve_creator("https://www.huya.com/998")
        self.assertEqual("huya", resolved.platform)
        self.assertEqual("998", resolved.platform_user_id)
        self.assertEqual("998", resolved.room_id)
        self.assertFalse(hasattr(resolved, "creator_id"))

    async def test_profile_requires_matching_room_identity(self) -> None:
        adapter, gateway = self._build()
        profile = await adapter.get_creator_profile(_account())
        self.assertEqual("998", profile.platform_user_id)
        gateway.profile = HuyaProfileRecord(room_id="1995", observed_at=NOW)
        with self.assertRaises(ProviderOperationError):
            await adapter.get_creator_profile(_account())

    async def test_e_live_status_2_maps_to_live(self) -> None:
        adapter, _ = self._build()
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.LIVE, snapshot.status)
        self.assertEqual(STARTED, snapshot.source_started_at)

    async def test_e_live_status_1_maps_to_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live = HuyaLiveRecord(
            room_id="998",
            observed_at=NOW,
            raw_live_status=1,
            source="huya.mobile_html",
            title="stale title",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.OFFLINE, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)

    async def test_body_class_cross_signals_map_without_numeric_guessing(self) -> None:
        adapter, gateway = self._build()
        for raw, expected in (
            ("liveStatus-on", LiveStatus.LIVE),
            ("liveStatus-off", LiveStatus.OFFLINE),
        ):
            with self.subTest(raw=raw):
                gateway.live = HuyaLiveRecord(
                    room_id="998",
                    observed_at=NOW,
                    raw_live_status=raw,
                    source="huya.mobile_html",
                    source_started_at=STARTED,
                )
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(expected, snapshot.status)

    async def test_unsupported_values_and_type_drift_stay_unknown(self) -> None:
        adapter, gateway = self._build()
        for raw in (None, 0, 3, -1, "0", "1", "2", True, False):
            with self.subTest(raw=raw):
                gateway.live = HuyaLiveRecord(
                    room_id="998",
                    observed_at=NOW,
                    raw_live_status=raw,
                    source="huya.mobile_html",
                    source_started_at=STARTED,
                )
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
                self.assertIsNone(snapshot.source_started_at)

    async def test_provider_failure_and_transport_failure_map_to_unknown(self) -> None:
        for error in (
            ProviderOperationError(
                ProviderFailure(ProviderFailureKind.RATE_LIMITED, "huya.mobile_html")
            ),
            TimeoutError("timeout"),
            ConnectionError("network"),
        ):
            with self.subTest(error=type(error).__name__):
                adapter, gateway = self._build()
                gateway.live_error = error
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    async def test_live_identity_mismatch_maps_to_unknown(self) -> None:
        adapter, gateway = self._build()
        gateway.live = HuyaLiveRecord(
            room_id="1995",
            observed_at=NOW,
            raw_live_status=2,
            source="huya.mobile_html",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)

    def test_formal_huya_adapter_has_no_legacy_or_state_engine_imports(self) -> None:
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
