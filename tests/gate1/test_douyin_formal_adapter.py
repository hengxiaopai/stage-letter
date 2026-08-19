from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.douyin import (
    DouyinFormalAdapter,
    DouyinIdentityRecord,
    DouyinLiveRecord,
    DouyinProfileRecord,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "douyin.py"
NOW = datetime(2026, 8, 19, 4, 30, tzinfo=timezone.utc)
STARTED = datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc)


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="100",
        creator_id="200",
        platform="douyin",
        platform_user_id="sec_uid_abc",
        room_id="900",
        canonical_url="https://www.douyin.com/user/sec_uid_abc",
    )


class _Gateway:
    def __init__(self) -> None:
        self.identity = DouyinIdentityRecord(
            sec_uid="sec_uid_abc",
            display_name="Creator",
            room_id="900",
            canonical_url="https://www.douyin.com/user/sec_uid_abc",
        )
        self.profile = DouyinProfileRecord(
            sec_uid="sec_uid_abc",
            observed_at=NOW,
            display_name="Creator",
            avatar_url="https://example.invalid/avatar.jpg",
            bio="bio",
        )
        self.live = DouyinLiveRecord(
            sec_uid="sec_uid_abc",
            observed_at=NOW,
            raw_status=2,
            source="streamget.profile",
            room_id="900",
            title="Live title",
            source_started_at=STARTED,
        )
        self.live_error: BaseException | None = None

    async def resolve_identity(self, input: str) -> DouyinIdentityRecord:
        return self.identity

    async def fetch_profile(self, sec_uid: str) -> DouyinProfileRecord:
        return self.profile

    async def fetch_live(self, sec_uid: str) -> DouyinLiveRecord:
        if self.live_error is not None:
            raise self.live_error
        return self.live


class DouyinFormalAdapterContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[DouyinFormalAdapter, _Gateway]:
        gateway = _Gateway()
        return DouyinFormalAdapter(gateway), gateway

    async def test_adapter_structurally_implements_formal_contract(self) -> None:
        adapter, _ = self._build()
        self.assertIsInstance(adapter, LivePlatformAdapter)

    async def test_resolve_creator_maps_provider_identity_without_internal_ids(self) -> None:
        adapter, _ = self._build()
        resolved = await adapter.resolve_creator("anything")
        self.assertEqual("douyin", resolved.platform)
        self.assertEqual("sec_uid_abc", resolved.platform_user_id)
        self.assertFalse(hasattr(resolved, "creator_id"))
        self.assertFalse(hasattr(resolved, "account_id"))

    async def test_profile_snapshot_requires_matching_stable_identity(self) -> None:
        adapter, gateway = self._build()
        snapshot = await adapter.get_creator_profile(_account())
        self.assertEqual("sec_uid_abc", snapshot.platform_user_id)
        gateway.profile = DouyinProfileRecord(sec_uid="other", observed_at=NOW)
        with self.assertRaises(ProviderOperationError):
            await adapter.get_creator_profile(_account())

    async def test_raw_status_2_maps_to_live(self) -> None:
        adapter, _ = self._build()
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.LIVE, snapshot.status)
        self.assertEqual(STARTED, snapshot.source_started_at)

    async def test_raw_status_4_maps_to_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live = DouyinLiveRecord(
            sec_uid="sec_uid_abc",
            observed_at=NOW,
            raw_status=4,
            source="streamget.profile",
            room_id="900",
            title="stale title says live",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.OFFLINE, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)
        self.assertEqual("stale title says live", snapshot.title)

    async def test_unrecognized_or_missing_status_stays_unknown(self) -> None:
        adapter, gateway = self._build()
        for raw in (0, 1, 3, None, "2", "4", "LIVE"):
            with self.subTest(raw=raw):
                gateway.live = DouyinLiveRecord(
                    sec_uid="sec_uid_abc",
                    observed_at=NOW,
                    raw_status=raw,
                    source="streamget.profile",
                    room_id="900",
                    source_started_at=STARTED,
                )
                snapshot = await adapter.get_live_snapshot(_account())
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
                self.assertIsNone(snapshot.source_started_at)

    async def test_provider_operation_failure_maps_to_unknown_not_offline(self) -> None:
        adapter, gateway = self._build()
        gateway.live_error = ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.PARSE_ERROR,
                source="streamget.profile",
            )
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)
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
        gateway.live = DouyinLiveRecord(
            sec_uid="wrong_identity",
            observed_at=NOW,
            raw_status=2,
            source="streamget.profile",
            room_id="900",
            source_started_at=STARTED,
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
        self.assertIsNone(snapshot.source_started_at)
        self.assertIsNone(snapshot.title)

    async def test_canonical_identity_url_comes_from_platform_account_not_room_metadata(self) -> None:
        adapter, gateway = self._build()
        gateway.live = DouyinLiveRecord(
            sec_uid="sec_uid_abc",
            observed_at=NOW,
            raw_status=4,
            source="streamget.profile",
            room_id="historical-room",
            title="old room title",
        )
        snapshot = await adapter.get_live_snapshot(_account())
        self.assertEqual("historical-room", snapshot.room_id)
        self.assertEqual(
            "https://www.douyin.com/user/sec_uid_abc",
            snapshot.canonical_url,
        )
        self.assertIs(LiveStatus.OFFLINE, snapshot.status)

    async def test_wrong_platform_account_is_rejected(self) -> None:
        adapter, _ = self._build()
        account = PlatformAccount(
            account_id="100",
            creator_id="200",
            platform="bilibili",
            platform_user_id="sec_uid_abc",
        )
        with self.assertRaises(ValueError):
            await adapter.get_live_snapshot(account)

    def test_formal_douyin_adapter_has_no_legacy_or_state_engine_imports(self) -> None:
        tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"), filename=str(ADAPTER_PATH))
        forbidden = (
            "platform_adapters",
            "experiments",
            "core",
            "api",
            "workers",
        )
        violations: list[str] = []
        source = ADAPTER_PATH.read_text(encoding="utf-8")
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
