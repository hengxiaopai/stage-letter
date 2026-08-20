"""Gate 2 formal detection-cycle runtime.

Due selection comes from Gate 2.1. Provider execution is delegated to the Gate
2.2 coordinator, while durable provider ingress remains the accepted Gate 1.4
MonitoringProbeApplicationService. Gate 2.3 appends operational telemetry only
after execution; telemetry failure never rewrites canonical live truth.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.application.services.monitoring_probe import (
    MonitoringProbeApplicationService,
    MonitoringProbeRequest,
    MonitoringProbeResult,
)
from stage_letter.detection.telemetry import ProbeTelemetryRecord
from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    RuntimeExecutionOutcome,
)
from workers.monitoring.scheduler import make_probe_id

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class DetectionTelemetryFailure:
    account_id: str
    error_type: str


@dataclass(frozen=True)
class DetectionCycleOutcome:
    cycle_id: str
    outcomes: tuple[RuntimeExecutionOutcome[MonitoringProbeResult], ...]
    telemetry_failures: tuple[DetectionTelemetryFailure, ...] = ()

    @property
    def succeeded(self) -> bool:
        """Provider/durable-ingress success is independent from telemetry health."""

        return all(item.succeeded for item in self.outcomes)

    @property
    def telemetry_complete(self) -> bool:
        return not self.telemetry_failures


class DetectionCycleRuntime:
    """Run one due-only cycle without bypassing the durable observation ingress."""

    def __init__(
        self,
        targets: DueMonitoringTargetApplicationService,
        probes: MonitoringProbeApplicationService,
        coordinator: DetectionRuntimeCoordinator,
        *,
        telemetry: DetectionTelemetryApplicationService | None = None,
        clock: Clock | None = None,
        page_size: int = 100,
    ) -> None:
        if page_size < 1 or page_size > targets.MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {targets.MAX_PAGE_SIZE}")
        self._targets = targets
        self._probes = probes
        self._coordinator = coordinator
        self._telemetry = telemetry
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._page_size = page_size

    async def _execute_account(
        self,
        *,
        cycle_id: str,
        account: PlatformAccount,
    ) -> tuple[
        RuntimeExecutionOutcome[MonitoringProbeResult],
        DetectionTelemetryFailure | None,
    ]:
        request = MonitoringProbeRequest(
            probe_id=make_probe_id(cycle_id, account.account_id),
            account_id=account.account_id,
        )

        async def operation() -> MonitoringProbeResult:
            return await self._probes.execute(request)

        started_at = self._clock()
        outcome = await self._coordinator.execute(account.platform, operation)
        finished_at = self._clock()
        if started_at.tzinfo is None or finished_at.tzinfo is None:
            raise ValueError("detection telemetry clock must return timezone-aware timestamps")

        telemetry_failure: DetectionTelemetryFailure | None = None
        if self._telemetry is not None:
            failure_kind = None
            observation_status = None
            if outcome.succeeded and outcome.value is not None:
                status = outcome.value.observation.status
                observation_status = getattr(status, "value", str(status))
            else:
                failure_kind = (
                    outcome.last_retry_decision.reason
                    if outcome.last_retry_decision is not None
                    else type(outcome.error).__name__
                )
            latency_ms = max(0, int(round((finished_at - started_at).total_seconds() * 1000)))
            record = ProbeTelemetryRecord(
                probe_id=request.probe_id,
                account_id=account.account_id,
                platform=account.platform,
                started_at=started_at,
                finished_at=finished_at,
                success=outcome.succeeded,
                attempts=outcome.attempts,
                latency_ms=latency_ms,
                observation_status=observation_status,
                failure_kind=failure_kind,
            )
            try:
                await self._telemetry.record(record)
            except Exception as exc:
                # Operational telemetry is valuable evidence but cannot roll back
                # a provider observation that was already durably persisted.
                telemetry_failure = DetectionTelemetryFailure(
                    account_id=account.account_id,
                    error_type=type(exc).__name__,
                )

        return outcome, telemetry_failure

    async def run_cycle(self, cycle_id: str) -> DetectionCycleOutcome:
        # Validate the stable logical probe namespace before target discovery I/O.
        make_probe_id(cycle_id, "validation")

        outcomes: list[RuntimeExecutionOutcome[MonitoringProbeResult]] = []
        telemetry_failures: list[DetectionTelemetryFailure] = []
        after_account_id: str | None = None
        while True:
            page = await self._targets.list_targets(
                after_account_id=after_account_id,
                limit=self._page_size,
            )
            if not page:
                break

            page_results = await asyncio.gather(
                *(
                    self._execute_account(cycle_id=cycle_id, account=account)
                    for account in page
                )
            )
            for outcome, telemetry_failure in page_results:
                outcomes.append(outcome)
                if telemetry_failure is not None:
                    telemetry_failures.append(telemetry_failure)
            after_account_id = page[-1].account_id
            if len(page) < self._page_size:
                break

        return DetectionCycleOutcome(
            cycle_id=cycle_id,
            outcomes=tuple(outcomes),
            telemetry_failures=tuple(telemetry_failures),
        )
