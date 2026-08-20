from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.detection_health import (
    HealthAwareDetectionTelemetryApplicationService,
)
from stage_letter.detection.contracts import PlatformHealthState
from stage_letter.detection.health import (
    CircuitBreakerPolicy,
    cadence_multiplier,
    normalize_platform_health_state,
    state_after_probe,
)
from stage_letter.detection.ports import DetectionScheduleRow
from stage_letter.detection.telemetry import (
    PlatformHealthSnapshot,
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)
from stage_letter.domain.creators import PlatformAccount

ROOT = Path(__file__).resolve().parents[2]
INFRA_HEALTH = ROOT / "stage_letter" / "infrastructure" / "detection" / "health.py"


def _account(account_id: str, platform: str = "douyin") -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform=platform,
        platform_user_id=f"provider-{account_id}",
        enabled=True,
    )


class _ScheduleRepo:
    def __init__(self, rows: tuple[DetectionScheduleRow, ...]) -> None:
        self.rows = rows

    async def list_schedule_rows(self, *, after_account_id=None, limit=100):
        if after_account_id is not None:
            return ()
        return self.rows[:limit]


def _health(state: PlatformHealthState, failures: int = 0) -> PlatformHealthSnapshot:
    return PlatformHealthSnapshot(
        platform="douyin",
        state=state,
        last_success_at=None,
        last_failure_at=None,
        success_count_24h=0,
        error_count_24h=0,
        success_rate_24h=None,
        avg_latency_ms_24h=None,
        consecutive_failures=failures,
    )


def test_circuit_breaker_policy_validation() -> None:
    policy = CircuitBreakerPolicy()
    assert policy.degraded_failure_threshold == 5
    assert policy.disabled_failure_threshold == 20
    assert policy.degraded_interval_multiplier == 5
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(degraded_failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(degraded_failure_threshold=5, disabled_failure_threshold=5)
    with pytest.raises(ValueError):
        CircuitBreakerPolicy(degraded_interval_multiplier=0)


def test_health_state_normalization_is_conservative() -> None:
    assert normalize_platform_health_state(None) is PlatformHealthState.HEALTHY
    assert normalize_platform_health_state("healthy") is PlatformHealthState.HEALTHY
    assert normalize_platform_health_state("DEGRADED") is PlatformHealthState.DEGRADED
    assert normalize_platform_health_state("DISABLED") is PlatformHealthState.DISABLED
    assert normalize_platform_health_state("corrupt") is PlatformHealthState.DEGRADED


def test_failure_thresholds() -> None:
    policy = CircuitBreakerPolicy()
    assert state_after_probe(
        current=PlatformHealthState.HEALTHY,
        success=False,
        consecutive_failures=4,
        policy=policy,
    ) is PlatformHealthState.HEALTHY
    assert state_after_probe(
        current=PlatformHealthState.HEALTHY,
        success=False,
        consecutive_failures=5,
        policy=policy,
    ) is PlatformHealthState.DEGRADED
    assert state_after_probe(
        current=PlatformHealthState.DEGRADED,
        success=False,
        consecutive_failures=20,
        policy=policy,
    ) is PlatformHealthState.DISABLED


def test_degraded_stays_degraded_until_success() -> None:
    policy = CircuitBreakerPolicy()
    assert state_after_probe(
        current=PlatformHealthState.DEGRADED,
        success=False,
        consecutive_failures=1,
        policy=policy,
    ) is PlatformHealthState.DEGRADED


def test_success_recovers_degraded_but_not_disabled() -> None:
    policy = CircuitBreakerPolicy()
    assert state_after_probe(
        current=PlatformHealthState.DEGRADED,
        success=True,
        consecutive_failures=0,
        policy=policy,
    ) is PlatformHealthState.HEALTHY
    assert state_after_probe(
        current=PlatformHealthState.DISABLED,
        success=True,
        consecutive_failures=0,
        policy=policy,
    ) is PlatformHealthState.DISABLED


def test_cadence_multiplier() -> None:
    policy = CircuitBreakerPolicy()
    assert cadence_multiplier(PlatformHealthState.HEALTHY, policy=policy) == 1
    assert cadence_multiplier(PlatformHealthState.DEGRADED, policy=policy) == 5
    assert cadence_multiplier(PlatformHealthState.DISABLED, policy=policy) is None


@pytest.mark.asyncio
async def test_due_selection_slows_degraded_platform() -> None:
    now = datetime(2026, 8, 20, 5, 0, 0, tzinfo=timezone.utc)
    row = DetectionScheduleRow(
        account=_account("1"),
        polling_tier_raw="warm",
        last_probe_at=now - timedelta(seconds=120),
        platform_health_state_raw="DEGRADED",
    )
    service = DueMonitoringTargetApplicationService(_ScheduleRepo((row,)), clock=lambda: now)
    assert await service.list_targets() == ()

    due_row = DetectionScheduleRow(
        account=_account("1"),
        polling_tier_raw="warm",
        last_probe_at=now - timedelta(seconds=300),
        platform_health_state_raw="DEGRADED",
    )
    service = DueMonitoringTargetApplicationService(_ScheduleRepo((due_row,)), clock=lambda: now)
    assert [item.account_id for item in await service.list_targets()] == ["1"]


@pytest.mark.asyncio
async def test_due_selection_excludes_disabled_platform() -> None:
    now = datetime(2026, 8, 20, 5, 0, 0, tzinfo=timezone.utc)
    row = DetectionScheduleRow(
        account=_account("2"),
        polling_tier_raw="hot",
        last_probe_at=now - timedelta(hours=1),
        platform_health_state_raw="DISABLED",
    )
    service = DueMonitoringTargetApplicationService(_ScheduleRepo((row,)), clock=lambda: now)
    assert await service.list_targets() == ()


@pytest.mark.asyncio
async def test_never_probed_degraded_is_still_due() -> None:
    now = datetime(2026, 8, 20, 5, 0, 0, tzinfo=timezone.utc)
    row = DetectionScheduleRow(
        account=_account("3"),
        polling_tier_raw="cold",
        last_probe_at=None,
        platform_health_state_raw="DEGRADED",
    )
    service = DueMonitoringTargetApplicationService(_ScheduleRepo((row,)), clock=lambda: now)
    assert [item.account_id for item in await service.list_targets()] == ["3"]


@pytest.mark.asyncio
async def test_health_aware_telemetry_applies_state_after_persistence() -> None:
    now = datetime(2026, 8, 20, 5, 1, 0, tzinfo=timezone.utc)
    calls: list[str] = []

    class BaseTelemetry:
        async def record(self, record):
            calls.append("telemetry")
            return ProbeTelemetryPersistenceResult(1, _health(PlatformHealthState.HEALTHY, 5))

    class HealthRepo:
        async def apply_probe_outcome(self, *, platform, success, at, policy):
            calls.append("health")
            assert platform == "douyin"
            assert success is False
            assert at == now
            return _health(PlatformHealthState.DEGRADED, 5)

    service = HealthAwareDetectionTelemetryApplicationService(
        BaseTelemetry(),  # type: ignore[arg-type]
        HealthRepo(),  # type: ignore[arg-type]
    )
    record = ProbeTelemetryRecord(
        probe_id="monitor:gate24",
        account_id="1",
        platform="douyin",
        started_at=now,
        finished_at=now,
        success=False,
        attempts=1,
        latency_ms=0,
        failure_kind="TIMEOUT",
    )
    result = await service.record(record)
    assert calls == ["telemetry", "health"]
    assert result.health.state is PlatformHealthState.DEGRADED


@pytest.mark.asyncio
async def test_health_aware_telemetry_does_not_apply_health_if_base_persistence_fails() -> None:
    now = datetime(2026, 8, 20, 5, 2, 0, tzinfo=timezone.utc)
    health_called = False

    class BaseTelemetry:
        async def record(self, record):
            raise RuntimeError("synthetic telemetry failure")

    class HealthRepo:
        async def apply_probe_outcome(self, **kwargs):
            nonlocal health_called
            health_called = True
            return _health(PlatformHealthState.HEALTHY)

    service = HealthAwareDetectionTelemetryApplicationService(
        BaseTelemetry(),  # type: ignore[arg-type]
        HealthRepo(),  # type: ignore[arg-type]
    )
    record = ProbeTelemetryRecord(
        probe_id="monitor:gate24-fail",
        account_id="1",
        platform="douyin",
        started_at=now,
        finished_at=now,
        success=True,
        attempts=1,
        latency_ms=0,
        observation_status="UNKNOWN",
    )
    with pytest.raises(RuntimeError):
        await service.record(record)
    assert health_called is False


def test_health_persistence_boundary_avoids_canonical_live_models() -> None:
    tree = ast.parse(INFRA_HEALTH.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "stage_letter.infrastructure.db.models" not in imports
    assert "stage_letter.infrastructure.db.base" not in imports
    source = INFRA_HEALTH.read_text(encoding="utf-8")
    assert '"platform_health"' in source
    assert "LiveSession" not in source
    assert "LiveEvent" not in source
    assert "NotificationDelivery" not in source
