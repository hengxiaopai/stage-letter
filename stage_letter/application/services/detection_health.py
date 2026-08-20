"""Gate 2.4 circuit-breaker application services."""
from __future__ import annotations

from datetime import datetime

from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.detection.health import CircuitBreakerPolicy
from stage_letter.detection.ports import DetectionHealthRepository
from stage_letter.detection.telemetry import (
    PlatformHealthSnapshot,
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)


class HealthAwareDetectionTelemetryApplicationService(DetectionTelemetryApplicationService):
    """Persist telemetry first, then reconcile operational circuit-breaker state.

    This Gate 2.4 enhancement deliberately remains a subtype of the accepted
    Gate 2.3 ``DetectionTelemetryApplicationService``. That preserves the frozen
    worker-composition contract while adding health reconciliation behind the
    same ``record()`` surface.

    Telemetry and health are operational evidence only. Any failure in this layer
    happens after provider/durable observation work and therefore cannot roll back
    canonical live truth or trigger a provider retry.
    """

    def __init__(
        self,
        telemetry: DetectionTelemetryApplicationService,
        health: DetectionHealthRepository,
        *,
        policy: CircuitBreakerPolicy | None = None,
    ) -> None:
        # ``record`` is intentionally overridden below and delegates to the
        # already-constructed Gate 2.3 service. We keep that service intact rather
        # than reaching into its private repository, while inheritance preserves
        # the accepted Gate 2.3 runtime type contract.
        self._telemetry = telemetry
        self._health = health
        self.policy = policy or CircuitBreakerPolicy()

    async def record(self, record: ProbeTelemetryRecord) -> ProbeTelemetryPersistenceResult:
        persisted = await self._telemetry.record(record)
        health = await self._health.apply_probe_outcome(
            platform=record.platform,
            success=record.success,
            at=record.finished_at,
            policy=self.policy,
        )
        return ProbeTelemetryPersistenceResult(
            probe_run_id=persisted.probe_run_id,
            health=health,
        )


class DetectionHealthAdministrationApplicationService:
    """Explicit operator controls for platform circuit-breaker state."""

    def __init__(self, repository: DetectionHealthRepository) -> None:
        self._repository = repository

    async def disable(self, *, platform: str, at: datetime) -> PlatformHealthSnapshot:
        return await self._repository.administrative_disable(platform=platform, at=at)

    async def enable_half_open(
        self,
        *,
        platform: str,
        at: datetime,
    ) -> PlatformHealthSnapshot:
        return await self._repository.administrative_enable(platform=platform, at=at)
