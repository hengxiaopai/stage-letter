"""Operational persistence ports for Gate 2 Detection Engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from stage_letter.detection.health import CircuitBreakerPolicy
from stage_letter.detection.telemetry import (
    PlatformHealthSnapshot,
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)
from stage_letter.domain.creators import PlatformAccount


@dataclass(frozen=True)
class DetectionScheduleRow:
    account: PlatformAccount
    polling_tier_raw: str | None
    last_probe_at: datetime | None
    platform_health_state_raw: str | None = None


class DetectionScheduleRepository(Protocol):
    async def list_schedule_rows(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = 100,
    ) -> tuple[DetectionScheduleRow, ...]: ...


class DetectionTelemetryRepository(Protocol):
    """Append operational probe evidence and refresh platform-health metrics."""

    async def record_probe(
        self,
        record: ProbeTelemetryRecord,
    ) -> ProbeTelemetryPersistenceResult: ...


class DetectionHealthRepository(Protocol):
    """Persist Gate 2.4 health-state transitions outside canonical live truth."""

    async def apply_probe_outcome(
        self,
        *,
        platform: str,
        success: bool,
        policy: CircuitBreakerPolicy,
    ) -> PlatformHealthSnapshot: ...

    async def administrative_disable(
        self,
        *,
        platform: str,
        at: datetime,
    ) -> PlatformHealthSnapshot: ...

    async def administrative_enable(
        self,
        *,
        platform: str,
        at: datetime,
    ) -> PlatformHealthSnapshot: ...
