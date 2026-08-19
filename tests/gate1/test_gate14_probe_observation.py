from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.errors import (
    ApplicationInvariantError,
    ApplicationNotFoundError,
)
from stage_letter.application.platforms import (
    CreatorProfileSnapshot,
    LiveSnapshot,
    ResolvedCreator,
)
from stage_letter.application.services.monitoring_probe import (
    MonitoringProbeApplicationService,
    MonitoringProbeRequest,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "monitoring_probe.py"


def _probe(name: str) -> str:
    return f"monitor:{name}"


def _account(*, enabled: bool = True) -> PlatformAccount:
    return PlatformAccount(
        account_id="101",
        creator_id="201",
        platform="douyin",
        platform_user_id="sec-101",
        canonical_url="https://www.douyin.com/user/sec-101",
        enabled=enabled,
    )


def _snapshot(
    *,
    status: LiveStatus = LiveStatus.LIVE,
    platform: str = "douyin",
    platform_user_id: str = "sec-101",
) -> LiveSnapshot:
    return LiveSnapshot(
        platform=platform,
        platform_user_id=platform_user_id,
        status=status,
        observed_at=datetime(2026, 8, 19, 7, 30, tzinfo=timezone.utc),
        source="provider.control",
        source_started_at=(
            datetime(2026, 8, 19, 7, 0, tzinfo=timezone.utc)
            if status is LiveStatus.LIVE
            else None
        ),
        title="metadata only",
    )


class _Creators:
    def __init__(self, account: PlatformAccount | None) -> None:
        self.account = account
        self.get_calls = 0

    async def get_account(self, account_id: str) -> PlatformAccount | None:
        self.get_calls += 1
        if self.account is None or self.account.account_id != account_id:
            return None
        return self.account


class _Live:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], LiveObservation] = {}
        self.get_calls = 0
        self.append_calls = 0
        self.insert_result = True

    async def get_observation(
        self,
        account_id: str,
        observation_id: str,
    ) -> LiveObservation | None:
        self.get_calls += 1
        return self.rows.get((account_id, observation_id))

    async def append_observation(self, observation: LiveObservation) -> bool:
        self.append_calls += 1
        if self.insert_result:
            self.rows[(observation.account_id, observation.observation_id)] = observation
        return self.insert_result


class _Uow:
    def __init__(self, creators: _Creators, live: _Live) -> None:
        self.creators = creators
        self.live = live
        self.active = False
        self.enter_count = 0
        self.commit_count = 0

    async def __aenter__(self):
        self.active = True
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.active = False
        return False

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class _Adapter:
    platform = "douyin"

    def __init__(
        self,
        snapshot: LiveSnapshot,
        *,
        uow: _Uow,
        on_live=None,
    ) -> None:
        self.snapshot = snapshot
        self.uow = uow
        self.on_live = on_live
        self.live_calls = 0

    async def resolve_creator(self, input: str) -> ResolvedCreator:
        return ResolvedCreator(platform="douyin", platform_user_id=input)

    async def get_creator_profile(
        self,
        account: PlatformAccount,
    ) -> CreatorProfileSnapshot:
        return CreatorProfileSnapshot(
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            observed_at=datetime.now(timezone.utc),
        )

    async def get_live_snapshot(self, account: PlatformAccount) -> LiveSnapshot:
        if self.uow.active:
            raise AssertionError("provider I/O must happen outside UnitOfWork")
        self.live_calls += 1
        if self.on_live is not None:
            self.on_live()
        return self.snapshot


class Gate14ProbeObservationContractTests(unittest.IsolatedAsyncioTestCase):
    def _service(
        self,
        *,
        account: PlatformAccount | None = None,
        snapshot: LiveSnapshot | None = None,
        on_live=None,
    ):
        creators = _Creators(_account() if account is None else account)
        live = _Live()
        uow = _Uow(creators, live)
        adapter = _Adapter(snapshot or _snapshot(), uow=uow, on_live=on_live)
        service = MonitoringProbeApplicationService(
            lambda: uow,  # type: ignore[arg-type]
            lambda platform: adapter,
        )
        return service, adapter, uow, live

    def test_probe_request_requires_bounded_stable_id(self) -> None:
        with self.assertRaises(ValueError):
            MonitoringProbeRequest(probe_id=" ", account_id="101")
        with self.assertRaises(ValueError):
            MonitoringProbeRequest(probe_id="probe-1", account_id="101")
        with self.assertRaises(ValueError):
            MonitoringProbeRequest(probe_id="monitor:" + "x" * 248, account_id="101")
        with self.assertRaises(ValueError):
            MonitoringProbeRequest(probe_id=_probe("probe-1"), account_id=" ")

    async def test_existing_probe_is_reused_without_provider_or_commit(self) -> None:
        service, adapter, uow, live = self._service()
        probe_id = _probe("probe-1")
        existing = LiveObservation(
            observation_id=probe_id,
            account_id="101",
            status=LiveStatus.OFFLINE,
            observed_at=datetime(2026, 8, 19, 7, 20, tzinfo=timezone.utc),
            source="old.source",
        )
        live.rows[("101", probe_id)] = existing

        result = await service.execute(MonitoringProbeRequest(probe_id, "101"))

        self.assertTrue(result.reused_existing)
        self.assertIs(existing, result.observation)
        self.assertEqual(0, adapter.live_calls)
        self.assertEqual(0, uow.commit_count)

    async def test_missing_account_fails_before_provider_call(self) -> None:
        creators = _Creators(None)
        live = _Live()
        uow = _Uow(creators, live)
        adapter = _Adapter(_snapshot(), uow=uow)
        service = MonitoringProbeApplicationService(
            lambda: uow,  # type: ignore[arg-type]
            lambda platform: adapter,
        )

        with self.assertRaises(ApplicationNotFoundError):
            await service.execute(MonitoringProbeRequest(_probe("probe-1"), "101"))
        self.assertEqual(0, adapter.live_calls)
        self.assertEqual(0, live.append_calls)

    async def test_disabled_account_fails_before_provider_call(self) -> None:
        service, adapter, _, live = self._service(account=_account(enabled=False))
        with self.assertRaises(ApplicationInvariantError):
            await service.execute(MonitoringProbeRequest(_probe("probe-1"), "101"))
        self.assertEqual(0, adapter.live_calls)
        self.assertEqual(0, live.append_calls)

    async def test_live_snapshot_is_persisted_as_one_observation_outside_uow(self) -> None:
        service, adapter, uow, live = self._service(snapshot=_snapshot())
        probe_id = _probe("probe-1")

        result = await service.execute(MonitoringProbeRequest(probe_id, "101"))

        self.assertFalse(result.reused_existing)
        self.assertEqual(1, adapter.live_calls)
        self.assertEqual(1, live.append_calls)
        self.assertEqual(1, uow.commit_count)
        self.assertEqual(probe_id, result.observation.observation_id)
        self.assertEqual("101", result.observation.account_id)
        self.assertIs(LiveStatus.LIVE, result.observation.status)
        self.assertEqual("provider.control", result.observation.source)
        self.assertEqual(_snapshot().source_started_at, result.observation.source_started_at)

    async def test_unknown_snapshot_is_persisted_as_unknown_not_offline(self) -> None:
        service, _, _, _ = self._service(snapshot=_snapshot(status=LiveStatus.UNKNOWN))
        result = await service.execute(MonitoringProbeRequest(_probe("unknown"), "101"))
        self.assertIs(LiveStatus.UNKNOWN, result.observation.status)
        self.assertIsNone(result.observation.source_started_at)

    async def test_snapshot_platform_mismatch_is_rejected_before_persistence(self) -> None:
        service, _, uow, live = self._service(snapshot=_snapshot(platform="huya"))
        with self.assertRaises(ApplicationInvariantError):
            await service.execute(MonitoringProbeRequest(_probe("probe-1"), "101"))
        self.assertEqual(0, live.append_calls)
        self.assertEqual(0, uow.commit_count)

    async def test_snapshot_identity_mismatch_is_rejected_before_persistence(self) -> None:
        service, _, uow, live = self._service(
            snapshot=_snapshot(platform_user_id="different")
        )
        with self.assertRaises(ApplicationInvariantError):
            await service.execute(MonitoringProbeRequest(_probe("probe-1"), "101"))
        self.assertEqual(0, live.append_calls)
        self.assertEqual(0, uow.commit_count)

    async def test_post_provider_recheck_reuses_work_completed_in_flight(self) -> None:
        service, adapter, uow, live = self._service()
        probe_id = _probe("race")
        existing = LiveObservation(
            observation_id=probe_id,
            account_id="101",
            status=LiveStatus.LIVE,
            observed_at=datetime(2026, 8, 19, 7, 29, tzinfo=timezone.utc),
            source="other.worker",
        )

        def complete_elsewhere() -> None:
            live.rows[("101", probe_id)] = existing

        adapter.on_live = complete_elsewhere
        result = await service.execute(MonitoringProbeRequest(probe_id, "101"))

        self.assertTrue(result.reused_existing)
        self.assertIs(existing, result.observation)
        self.assertEqual(1, adapter.live_calls)
        self.assertEqual(0, live.append_calls)
        self.assertEqual(0, uow.commit_count)

    def test_probe_service_and_repository_keep_formal_boundaries(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SERVICE_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "platform_adapters",
            "experiments",
            "workers",
            "api",
            "sqlalchemy",
            "httpx",
            "requests",
            "streamget",
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
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("Notification", source)

        method = SQLAlchemyLiveRepository.get_observation
        self.assertTrue(inspect.iscoroutinefunction(method))
        parameters = inspect.signature(method).parameters
        self.assertEqual(("self", "account_id", "observation_id"), tuple(parameters))
        repository_source = inspect.getsource(method)
        self.assertNotIn("source ==", repository_source)
        self.assertIn("LiveObservationModel.observation_id == observation_id", repository_source)


if __name__ == "__main__":
    unittest.main()
