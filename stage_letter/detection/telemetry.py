"""Operational telemetry contracts for Gate 2.3 Detection Engine.

Telemetry describes how one logical monitoring probe executed. It is not live
truth: `success=True` means the formal probe operation completed/persisted, even
when the resulting LiveObservation status is UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from stage_letter.detection.contracts import PlatformHealthState


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProbeTelemetryRecord:
    probe_id: str
    account_id: str
    platform: str
    started_at: datetime
    finished_at: datetime
    success: bool
    attempts: int
    latency_ms: int
    observation_status: str | None = None
    failure_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.probe_id.startswith("monitor:"):
            raise ValueError("probe_id must use the formal monitor: namespace")
        if not self.account_id.strip():
            raise ValueError("account_id is required")
        if not self.platform.strip():
            raise ValueError("platform is required")
        started = _utc(self.started_at, field="started_at")
        finished = _utc(self.finished_at, field="finished_at")
        if finished < started:
            raise ValueError("finished_at must be >= started_at")
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.success and self.failure_kind is not None:
            raise ValueError("successful telemetry must not carry failure_kind")
        if not self.success and not (self.failure_kind or "").strip():
            raise ValueError("failed telemetry requires failure_kind")


@dataclass(frozen=True)
class PlatformHealthSnapshot:
    platform: str
    state: PlatformHealthState
    last_success_at: datetime | None
    last_failure_at: datetime | None
    success_count_24h: int
    error_count_24h: int
    success_rate_24h: float | None
    avg_latency_ms_24h: int | None
    consecutive_failures: int


@dataclass(frozen=True)
class ProbeTelemetryPersistenceResult:
    probe_run_id: int
    health: PlatformHealthSnapshot
