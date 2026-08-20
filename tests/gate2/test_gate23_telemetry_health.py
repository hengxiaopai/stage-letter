from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stage_letter.application.services.monitoring_probe import MonitoringProbeResult
from stage_letter.detection.telemetry import ProbeTelemetryRecord
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)
from workers.detection_runtime import DetectionCycleRuntime

ROOT = Path(__file__).resolve().parents[2]
INFRA_TELEMETRY = ROOT / "stage_letter" / "infrastructure" / "detection" / "telemetry.py"


def _account(account_id: str = "1", platform: str = "douyin") -> PlatformAccount:
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
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return await self.handler(request)


class _Telemetry:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.records: list[ProbeTelemetryRecord] = []

    async def record(self, record: ProbeTelemetryRecord):
        self.records.append(record)
        if self.fail:
            raise RuntimeError("synthetic telemetry outage")
        return None


def _result(request, status: LiveStatus = LiveStatus.UNKNOWN) -> MonitoringProbeResult:
    return MonitoringProbeResult(
        observation=LiveObservation(
            observation_id=request.probe_id,
            account_id=request.account_id,
            status=status,
            observed_at=datetime.now(timezone.utc),
            source="gate2.3.synthetic",
        ),
        reused_existing=False,
    )


def _coordinator(*, attempts: int = 2) -> DetectionRuntimeCoordinator:
    async def no_wait(_: float) -> None:
        return None

    return DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=attempts,
            base_backoff_seconds=0,
        ),
        sleep=no_wait,
    )


def _clock(*values: datetime):
    queue = list(values)

    def now() -> datetime:
        return queue.pop(0)

    return now


def test_successful_unknown_is_valid_operational_success() -> None:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    record = ProbeTelemetryRecord(
        probe_id="monitor:test",
        account_id="1",
        platform="douyin",
        started_at=now,
        finished_at=now + timedelta(milliseconds=50),
        success=True,
        attempts=1,
        latency_ms=50,
        observation_status="UNKNOWN",
    )
    assert record.success is True
    assert record.observation_status == "UNKNOWN"
    assert record.failure_kind is None


def test_failed_telemetry_requires_failure_kind() -> None:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="failure_kind"):
        ProbeTelemetryRecord(
            probe_id="monitor:test",
            account_id="1",
            platform="douyin",
            started_at=now,
            finished_at=now,
            success=False,
            attempts=1,
            latency_ms=0,
        )


def test_telemetry_rejects_invalid_attempt_latency_and_time() -> None:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    common = dict(
        probe_id="monitor:test",
        account_id="1",
        platform="douyin",
        started_at=now,
        finished_at=now,
        success=True,
    )
    with pytest.raises(ValueError, match="attempts"):
        ProbeTelemetryRecord(**common, attempts=0, latency_ms=0)
    with pytest.raises(ValueError, match="latency"):
        ProbeTelemetryRecord(**common, attempts=1, latency_ms=-1)
    with pytest.raises(ValueError, match="finished_at"):
        ProbeTelemetryRecord(
            **{**common, "finished_at": now - timedelta(seconds=1)},
            attempts=1,
            latency_ms=0,
        )


@pytest.mark.asyncio
async def test_runtime_records_success_after_durable_probe() -> None:
    async def handler(request):
        return _result(request, LiveStatus.UNKNOWN)

    telemetry = _Telemetry()
    start = datetime(2026, 8, 20, 4, 0, 0, tzinfo=timezone.utc)
    runtime = DetectionCycleRuntime(
        _Targets((_account(),)),
        _Probe(handler),  # type: ignore[arg-type]
        _coordinator(),
        telemetry=telemetry,  # type: ignore[arg-type]
        clock=_clock(start, start + timedelta(milliseconds=250)),
    )
    result = await runtime.run_cycle("telemetry-success")

    assert result.succeeded
    assert result.telemetry_complete
    assert len(telemetry.records) == 1
    record = telemetry.records[0]
    assert record.success is True
    assert record.observation_status == "UNKNOWN"
    assert record.attempts == 1
    assert record.latency_ms == 250
    assert record.failure_kind is None


@pytest.mark.asyncio
async def test_runtime_records_retry_attempt_count_without_changing_probe_identity() -> None:
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("synthetic")
        return _result(request, LiveStatus.OFFLINE)

    probe = _Probe(handler)
    telemetry = _Telemetry()
    start = datetime(2026, 8, 20, 4, 1, 0, tzinfo=timezone.utc)
    runtime = DetectionCycleRuntime(
        _Targets((_account(),)),
        probe,  # type: ignore[arg-type]
        _coordinator(attempts=2),
        telemetry=telemetry,  # type: ignore[arg-type]
        clock=_clock(start, start + timedelta(milliseconds=30)),
    )
    result = await runtime.run_cycle("telemetry-retry")

    assert result.succeeded
    assert len(probe.calls) == 2
    assert len({item.probe_id for item in probe.calls}) == 1
    assert telemetry.records[0].attempts == 2
    assert telemetry.records[0].success is True


@pytest.mark.asyncio
async def test_auth_failure_is_recorded_not_blindly_retried() -> None:
    async def handler(request):
        raise ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.AUTH_REQUIRED,
                source="gate2.3.synthetic",
            )
        )

    probe = _Probe(handler)
    telemetry = _Telemetry()
    start = datetime(2026, 8, 20, 4, 2, 0, tzinfo=timezone.utc)
    runtime = DetectionCycleRuntime(
        _Targets((_account(),)),
        probe,  # type: ignore[arg-type]
        _coordinator(attempts=3),
        telemetry=telemetry,  # type: ignore[arg-type]
        clock=_clock(start, start + timedelta(milliseconds=10)),
    )
    result = await runtime.run_cycle("telemetry-auth")

    assert result.succeeded is False
    assert len(probe.calls) == 1
    assert telemetry.records[0].success is False
    assert telemetry.records[0].failure_kind == "AUTH_REQUIRED"
    assert telemetry.records[0].attempts == 1


@pytest.mark.asyncio
async def test_telemetry_persistence_failure_cannot_reverse_provider_success() -> None:
    async def handler(request):
        return _result(request, LiveStatus.LIVE)

    telemetry = _Telemetry(fail=True)
    start = datetime(2026, 8, 20, 4, 3, 0, tzinfo=timezone.utc)
    runtime = DetectionCycleRuntime(
        _Targets((_account(),)),
        _Probe(handler),  # type: ignore[arg-type]
        _coordinator(),
        telemetry=telemetry,  # type: ignore[arg-type]
        clock=_clock(start, start + timedelta(milliseconds=10)),
    )
    result = await runtime.run_cycle("telemetry-outage")

    assert result.succeeded is True
    assert result.telemetry_complete is False
    assert len(result.telemetry_failures) == 1
    assert result.telemetry_failures[0].account_id == "1"
    assert result.telemetry_failures[0].error_type == "RuntimeError"


def test_successful_record_cannot_carry_failure_kind() -> None:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="successful telemetry"):
        ProbeTelemetryRecord(
            probe_id="monitor:test",
            account_id="1",
            platform="douyin",
            started_at=now,
            finished_at=now,
            success=True,
            attempts=1,
            latency_ms=0,
            failure_kind="TIMEOUT",
        )


def test_operational_repository_stays_outside_canonical_base() -> None:
    tree = ast.parse(INFRA_TELEMETRY.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "stage_letter.infrastructure.db.models" not in imports
    assert "stage_letter.infrastructure.db.base" not in imports
    source = INFRA_TELEMETRY.read_text(encoding="utf-8")
    assert '"probe_runs"' in source
    assert '"platform_health"' in source
    assert "TELEMETRY_SCHEMA = \"gate2.3\"" in source


def test_telemetry_contract_contains_no_notification_or_live_mutation_api() -> None:
    source = (ROOT / "stage_letter" / "detection" / "telemetry.py").read_text(encoding="utf-8")
    assert "NotificationDelivery" not in source
    assert "LiveSession" not in source
    assert "LiveEvent" not in source
