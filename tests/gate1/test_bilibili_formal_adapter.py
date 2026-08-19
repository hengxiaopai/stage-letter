from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.bilibili import (
    BilibiliFormalAdapter,
    BilibiliIdentityRecord,
    BilibiliLiveRecord,
    BilibiliProfileRecord,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "bilibili.py"
NOW = datetime(2026, 8, 19, 5, 40, tzinfo=timezone.utc)
STARTED = datetime(2026, 8, 19, 5, 0, tzinfo=timezone.utc)


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="301",
        creator_id="401",
        platform="bilibili",
        platform_user_id="528738158",
        room_id="8758725",
        canonical_url="https://space.bilibili.com/528738158",
    )


class _Gateway:
    def __init__(self) -> None:
        self.identity = BilibiliIdentityRecord(
            uid="528738158",
            display_name="Creator",
            room_id="8758725",
            canonical_url="https://space.bilibili.com/528738158",
        )
        self.profile = BilibiliProfileRecord(
            uid="528738158",
            observed_at=NOW,
            display_name="Creator",
        )
        self.live = BilibiliLiveRecord(
            uid="528738158",
            observed_at=NOW,
            raw_live_status=1,
            source="bilibili.getRoomInfoOld",
            room_id="8758725",
            title="Live title",
            source_started_at=STARTED,
        )
        self.live_error: BaseException | None = None

    async def resolve_identity(self, input: str) -> BilibiliIdentityRecord:
        return self.identity

    async def fetch_profile(self, uid: str) -> BilibiliProfileRecord:
        return self.profile

    async def fetch_live(self, uid: str) -> BilibiliLiveRecord:
        if self.live_error is not None:
            raise self.live_error
        return self.live


class BilibiliFormalAdapterContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[BilibiliFormalAdapter, _Gateway]:
        gateway = _Gateway()
        return BilibiliFormalAdapter(gateway), gateway

    async def test_adapter_structurally_implements_formal_contract(self) -> None:
        adapter, _ = self._build()
        self.assertIsInstance(adapter, LivePlatformAdapter)

    async def test_resolve_creator_uses_uid_as_external_identity(self) -> None:
        adapter, _ = self._build()
        resolved = await adapter.resolve_creator("https://space.bilibili.com/528738158")
        self.assertEqual("bilibili", resolved.platform)
        self.assertEqual("528738158", resolved.platform_user_id)
        self.assertFalse(hasattr(resolved, "creator_id"))
        self.assertFalse(hasattr(resolved, "account_id"))

    async def test_profile_requires_matching_uid(self) -> None:
        adapter, gateway = self._build()
        profile = await adapter.get_creator_profile(_account())
        self.assertEqual("528738158", profile.platform_user_id)
        gateway.profile = BilibiliProfileRecord(uid="other", observed_at=NOW)
        with self.assertRaises(ProviderOperationError):
            await adapter.get_creator_profile(_account())

    async def test_live_status_1_maps_to_live(self) -> None:
        adapter, _ = self._build()
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.LIVE, snapshot.status)
        self.assertEqual(STARTED, snapshot.source_started_at)

    async def test_live_status_2_carousel_maps_to_live(self) -> None:
        adapter, gateway = self._build()
        gateway.live = BilibiliLiveRecord(
            uid="528738158",
            observed_at=NOW,
            raw_live_status=2,
            source="bilibili.getRoomInfoOld",
            room_id="8758725",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.LIVE, snapshot.status)
        self.assertEqual(STARTED, snapshot.source_started_at)

    async def test_live_status_0_maps_to_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live = BilibiliLiveRecord(
            uid="528738158",
            observed_at=NOW,
            raw_live_status=0,
            source="bilibili.getRoomInfoOld",
            room_id="8758725",
            title="stale title",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.OFFLINE, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)
        self.assertEqual("stale title", snapshot.title)

    async def test_unrecognized_or_type_drift_stays_unknown(self) -> None:
        adapter, gateway = self._build()
        for raw in (None, 3, -1, "0", "1", "2", True, False):
            with self.subTest(raw=raw):
                gateway.live = BilibiliLiveRecord(
                    uid="528738158",
                    observed_at=NOW,
                    raw_live_status=raw,
                    source="bilibili.getRoomInfoOld",
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
                source="bilibili.getRoomInfoOld",
            )
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.title)

    async def test_timeout_and_network_failure_map_to_unknown(self) -> None:
        for error in (TimeoutError("timeout"), ConnectionError("network")):
            with self.subTest(error=type(error).__name__):
                adapter, gateway = self._build()
                gateway.live_error = error
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    async def test_live_identity_mismatch_maps_to_unknown(self) -> None:
        adapter, gateway = self._build()
        gateway.live = BilibiliLiveRecord(
            uid="other",
            observed_at=NOW,
            raw_live_status=1,
            source="bilibili.getRoomInfoOld",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)

    def test_formal_bilibili_adapter_has_no_legacy_or_state_engine_imports(self) -> None:
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
