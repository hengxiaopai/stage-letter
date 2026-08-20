"""Gate 2.3 operational telemetry persistence service."""
from __future__ import annotations

from stage_letter.detection.ports import DetectionTelemetryRepository
from stage_letter.detection.telemetry import (
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)


class DetectionTelemetryApplicationService:
    """Persist one logical probe's operational evidence.

    This service intentionally has no canonical UnitOfWork dependency. Failure to
    persist telemetry must never fabricate or rewrite LiveObservation/Session/Event
    truth; callers decide how to surface telemetry incompleteness.
    """

    def __init__(self, repository: DetectionTelemetryRepository) -> None:
        self._repository = repository

    async def record(
        self,
        record: ProbeTelemetryRecord,
    ) -> ProbeTelemetryPersistenceResult:
        return await self._repository.record_probe(record)
