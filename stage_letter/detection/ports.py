"""Operational persistence ports for Gate 2 Detection Engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from stage_letter.detection.telemetry import (
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)
from stage_letter.domain.creators import PlatformAccount


@dataclass(frozen=True)
class DetectionScheduleRow:
    account: PlatformAccount
    polling_tier_raw: str | None
    last_probe_at: datetime | None


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
