from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.application.services.monitoring_probe import MonitoringProbeResult
from stage_letter.detection.lease import (
    DetectionLeaseAcquireResult,
    DetectionLeasePolicy,
    DetectionProbeLease,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
)
from workers.detection_composition import build_detection_runtime
from workers.detection_runtime import DetectionCycleRuntime

ROOT = Path(__file__).resolve().parents[2]


def _account(account_id: str, platform: str = "bilibili") -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform=platform,
        platform_user_id=f"provider-{account_id}",
        enabled=True,
    )


class _Targets:
    MAX_PAGE_SIZE = 1000

    def __init__(self, accounts: tuple[PlatformAccount, ...]) -> None:
        self.accounts = accounts

    async def list_targets(self, *, after_account_id=None, limit=100):
        if after_account_id is not None:
            return ()
        return self.accounts[:limit]


class _Probe:
    def __init__(self, *, started: asyncio.Event | None = None, release: asyncio.Event | None = None):
        self.calls = []
        self.started = started
        self.release = release

    async def execute(self, request):
        self.calls.append(request)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return MonitoringProbeResult(
            observation=LiveObservation(
                observation_id=request.probe_id,
                account_id=request.account_id,
                status=LiveStatus.UNKNOWN,
                observed_at=datetime.now(timezone.utc),
                source="gate2.5.synthetic",
            ),
            reused_existing=False,
        )


def _coordinator() -> DetectionRuntimeCoordinator:
    return DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=4,
            max_platform_concurrency=2,
            requests_per_second=1_000_000,
            max_attempts=1,
        )
    )


def _lease(account_id: str, probe_id: str, owner: str) -> DetectionProbeLease:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    return DetectionProbeLease(
        account_id=account_id,
        probe_id=probe_id,
        owner_token=owner,
        acquired_at=now,
        lease_expires_at=now + timedelta(seconds=120),
    )


class _LeaseService:
    def __init__(self, *, acquire: bool = True, acquire_error: Exception | None = None, release_result: bool = True):
        self.acquire = acquire
        self.acquire_error = acquire_error
        self.release_result = release_result
        self.owner: str | None = None
        self.acquire_calls = []
        self.release_calls = []

    async def try_acquire(self, *, account_id, probe_id, owner_token):
        self.acquire_calls.append((account_id, probe_id, owner_token))
        if self.acquire_error is not None:
            raise self.acquire_error
        if not self.acquire:
            return DetectionLeaseAcquireResult(acquired=False)
        self.owner = owner_token
        return DetectionLeaseAcquireResult(
            acquired=True,
            lease=_lease(account_id, probe_id, owner_token),
        )

    async def release(self, *, account_id, owner_token):
        self.release_calls.append((account_id, owner_token))
        return self.release_result


class _SharedLeaseService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: str | None = None

    async def try_acquire(self, *, account_id, probe_id, owner_token):
        async with self._lock:
            if self._owner is not None:
                return DetectionLeaseAcquireResult(acquired=False)
            self._owner = owner_token
            return DetectionLeaseAcquireResult(
                acquired=True,
                lease=_lease(account_id, probe_id, owner_token),
            )

    async def release(self, *, account_id, owner_token):
        async with self._lock:
            if self._owner != owner_token:
                return False
            self._owner = None
            return True


def test_detection_lease_policy_rejects_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="lease_seconds"):
        DetectionLeasePolicy(lease_seconds=0)


def test_detection_probe_lease_requires_monitor_namespace_and_future_expiry() -> None:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="monitor"):
        DetectionProbeLease("1", "manual:x", "worker", now, now + timedelta(seconds=1))
    with pytest.raises(ValueError, match="after acquired"):
        DetectionProbeLease("1", "monitor:x", "worker", now, now)


def test_detection_lease_acquire_result_is_self_consistent() -> None:
    with pytest.raises(ValueError, match="lease presence"):
        DetectionLeaseAcquireResult(acquired=True, lease=None)


def test_runtime_requires_owner_token_when_leases_enabled() -> None:
    with pytest.raises(ValueError, match="owner_token"):
        DetectionCycleRuntime(
            _Targets((_account("1"),)),  # type: ignore[arg-type]
            _Probe(),  # type: ignore[arg-type]
            _coordinator(),
            leases=_LeaseService(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_held_lease_skips_provider_without_marking_cycle_failed() -> None:
    probe = _Probe()
    runtime = DetectionCycleRuntime(
        _Targets((_account("1"),)),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        _coordinator(),
        leases=_LeaseService(acquire=False),  # type: ignore[arg-type]
        owner_token="worker-b",
    )
    result = await runtime.run_cycle("shared-cycle")
    assert result.succeeded
    assert result.outcomes == ()
    assert len(result.lease_skips) == 1
    assert result.lease_skips[0].reason == "LEASE_HELD"
    assert probe.calls == []


@pytest.mark.asyncio
async def test_lease_acquisition_failure_prevents_provider_and_surfaces_failure() -> None:
    probe = _Probe()
    runtime = DetectionCycleRuntime(
        _Targets((_account("1"),)),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        _coordinator(),
        leases=_LeaseService(acquire_error=RuntimeError("db down")),  # type: ignore[arg-type]
        owner_token="worker-a",
    )
    result = await runtime.run_cycle("lease-db-down")
    assert result.succeeded is False
    assert result.outcomes == ()
    assert result.lease_failures[0].error_type == "RuntimeError"
    assert probe.calls == []


@pytest.mark.asyncio
async def test_successful_provider_execution_releases_owned_lease() -> None:
    leases = _LeaseService()
    probe = _Probe()
    runtime = DetectionCycleRuntime(
        _Targets((_account("1"),)),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        _coordinator(),
        leases=leases,  # type: ignore[arg-type]
        owner_token="worker-a",
    )
    result = await runtime.run_cycle("release-success")
    assert result.succeeded
    assert len(result.outcomes) == 1
    assert len(probe.calls) == 1
    assert leases.release_calls == [("1", "worker-a")]
    assert result.lease_failures == ()


@pytest.mark.asyncio
async def test_failed_release_never_replays_provider_and_is_operational_failure() -> None:
    leases = _LeaseService(release_result=False)
    probe = _Probe()
    runtime = DetectionCycleRuntime(
        _Targets((_account("1"),)),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        _coordinator(),
        leases=leases,  # type: ignore[arg-type]
        owner_token="worker-a",
    )
    result = await runtime.run_cycle("release-failure")
    assert len(probe.calls) == 1
    assert len(result.outcomes) == 1
    assert result.outcomes[0].succeeded
    assert result.succeeded is False
    assert result.lease_failures[0].error_type == "LEASE_NOT_OWNED"


@pytest.mark.asyncio
async def test_lease_contention_on_one_account_does_not_block_other_account() -> None:
    class SelectiveLease(_LeaseService):
        async def try_acquire(self, *, account_id, probe_id, owner_token):
            if account_id == "1":
                return DetectionLeaseAcquireResult(acquired=False)
            return await super().try_acquire(
                account_id=account_id,
                probe_id=probe_id,
                owner_token=owner_token,
            )

    probe = _Probe()
    runtime = DetectionCycleRuntime(
        _Targets((_account("1", "douyin"), _account("2", "bilibili"))),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        _coordinator(),
        leases=SelectiveLease(),  # type: ignore[arg-type]
        owner_token="worker-b",
    )
    result = await runtime.run_cycle("mixed-contention")
    assert result.succeeded
    assert [call.account_id for call in probe.calls] == ["2"]
    assert [skip.account_id for skip in result.lease_skips] == ["1"]


@pytest.mark.asyncio
async def test_two_runtime_instances_same_cycle_execute_provider_once_while_lease_live() -> None:
    shared = _SharedLeaseService()
    started = asyncio.Event()
    release = asyncio.Event()
    probe_a = _Probe(started=started, release=release)
    probe_b = _Probe()
    targets = _Targets((_account("1"),))
    runtime_a = DetectionCycleRuntime(
        targets,  # type: ignore[arg-type]
        probe_a,  # type: ignore[arg-type]
        _coordinator(),
        leases=shared,  # type: ignore[arg-type]
        owner_token="worker-a",
    )
    runtime_b = DetectionCycleRuntime(
        targets,  # type: ignore[arg-type]
        probe_b,  # type: ignore[arg-type]
        _coordinator(),
        leases=shared,  # type: ignore[arg-type]
        owner_token="worker-b",
    )

    task_a = asyncio.create_task(runtime_a.run_cycle("same-cycle"))
    await started.wait()
    result_b = await runtime_b.run_cycle("same-cycle")
    release.set()
    result_a = await task_a

    assert result_a.succeeded
    assert result_b.succeeded
    assert len(probe_a.calls) == 1
    assert probe_b.calls == []
    assert len(result_b.lease_skips) == 1
    assert result_a.outcomes[0].value.observation.observation_id == probe_a.calls[0].probe_id  # type: ignore[union-attr]


def test_gate25_composition_is_io_free_and_preserves_gate23_telemetry_contract() -> None:
    def forbidden_session_factory():
        raise AssertionError("composition must not open DB I/O")

    a = build_detection_runtime(forbidden_session_factory)  # type: ignore[arg-type]
    b = build_detection_runtime(forbidden_session_factory)  # type: ignore[arg-type]
    assert isinstance(a.telemetry, DetectionTelemetryApplicationService)
    assert a.runtime._leases is a.leases
    assert a.runtime._owner_token == a.worker_token
    assert a.worker_token != b.worker_token
    assert len(a.worker_token) <= 64


def test_gate25_lease_storage_stays_operational_and_outside_canonical_base() -> None:
    source = (ROOT / "stage_letter" / "infrastructure" / "detection" / "leases.py").read_text(
        encoding="utf-8"
    )
    migration = (
        ROOT / "migrations" / "versions" / "b25d4e9c7a12_gate25_detection_probe_leases.py"
    ).read_text(encoding="utf-8")
    assert '"detection_probe_leases"' in source
    assert "stage_letter.infrastructure.db.models" not in source
    assert "stage_letter.infrastructure.db.base" not in source
    assert 'revision: str = "b25d4e9c7a12"' in migration
    assert 'down_revision: Union[str, Sequence[str], None] = "a63f4b2d9e71"' in migration
    assert "exactly-once provider guarantee" in (
        ROOT / "stage_letter" / "detection" / "lease.py"
    ).read_text(encoding="utf-8")
