"""Gate 2 formal detection-cycle runtime.

Due selection comes from Gate 2.1. Provider execution is delegated to the Gate
2.2 coordinator, while durable provider ingress remains the accepted Gate 1.4
MonitoringProbeApplicationService. Gate 2.3 appends operational telemetry only
after execution; Gate 2.5 optionally guards provider execution with a durable
cross-worker account lease.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.detection_lease import DetectionLeaseApplicationService
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
class DetectionLeaseSkip:
    account_id: str
    platform: str
    reason: str = "LEASE_HELD"


@dataclass(frozen=True)
class DetectionLeaseFailure:
    account_id: str
    error_type: str


@dataclass(frozen=True)
class DetectionCycleOutcome:
    cycle_id: str
    outcomes: tuple[RuntimeExecutionOutcome[MonitoringProbeResult], ...]
    telemetry_failures: tuple[DetectionTelemetryFailure, ...] = ()
    lease_skips: tuple[DetectionLeaseSkip, ...] = ()
    lease_failures: tuple[DetectionLeaseFailure, ...] = ()

    @property
    def succeeded(self) -> bool:
        """Lease contention is normal; lease infrastructure failure is not."""

        return all(item.succeeded for item in self.outcomes) and not self.lease_failures

    @property
    def telemetry_complete(self) -> bool:
        return not self.telemetry_failures


class DetectionCycleRuntime:
    """Run one due-only cycle without bypassing durable observation ingress."""

    def __init__(
        self,
        targets: DueMonitoringTargetApplicationService,
        probes: MonitoringProbeApplicationService,
        coordinator: DetectionRuntimeCoordinator,
        *,
        telemetry: DetectionTelemetryApplicationService | None = None,
        leases: DetectionLeaseApplicationService | None = None,
        owner_token: str | None = None,
        clock: Clock | None = None,
        page_size: int = 100,
    ) -> None:
        if page_size < 1 or page_size > targets.MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {targets.MAX_PAGE_SIZE}")
        if leases is not None and (owner_token is None or not owner_token.strip()):
            raise ValueError("owner_token is required when durable leases are enabled")
        if owner_token is not None and len(owner_token) > 64:
            raise ValueError("owner_token must fit detection lease storage")
        self._targets = targets
        self._probes = probes
        self._coordinator = coordinator
        self._telemetry = telemetry
        self._leases = leases
        self._owner_token = owner_token
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._page_size = page_size

    async def _execute_account(
        self,
        *,
        cycle_id: str,
        account: PlatformAccount,
    ) -> tuple[
        RuntimeExecutionOutcome[MonitoringProbeResult] | None,
        DetectionTelemetryFailure | None,
        DetectionLeaseSkip | None,
        DetectionLeaseFailure | None,
    ]:
        request = MonitoringProbeRequest(
            probe_id=make_probe_id(cycle_id, account.account_id),
            account_id=account.account_id,
        )

        lease_acquired = False
        if self._leases is not None:
            assert self._owner_token is not None
            try:
                acquisition = await self._leases.try_acquire(
                    account_id=account.account_id,
                    probe_id=request.probe_id,
                    owner_token=self._owner_token,
                )
            except Exception as exc:
                return (
                    None,
                    None,
                    None,
                    DetectionLeaseFailure(
                        account_id=account.account_id,
                        error_type=type(exc).__name__,
                    ),
                )
            if not acquisition.acquired:
                return (
                    None,
                    None,
                    DetectionLeaseSkip(
                        account_id=account.account_id,
                        platform=account.platform,
                    ),
                    None,
                )
            lease_acquired = True

        async def operation() -> MonitoringProbeResult:
            return await self._probes.execute(request)

        outcome: RuntimeExecutionOutcome[MonitoringProbeResult]
        telemetry_failure: DetectionTelemetryFailure | None = None
        lease_failure: DetectionLeaseFailure | None = None
        try:
            started_at = self._clock()
            outcome = await self._coordinator.execute(account.platform, operation)
            finished_at = self._clock()
            if started_at.tzinfo is None or finished_at.tzinfo is None:
                raise ValueError("detection telemetry clock must return timezone-aware timestamps")

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
                latency_ms = max(
                    0,
                    int(round((finished_at - started_at).total_seconds() * 1000)),
                )
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
                    # Operational telemetry cannot roll back durable live truth.
                    telemetry_failure = DetectionTelemetryFailure(
                        account_id=account.account_id,
                        error_type=type(exc).__name__,
                    )
        finally:
            if lease_acquired:
                assert self._leases is not None
                assert self._owner_token is not None
                try:
                    released = await self._leases.release(
                        account_id=account.account_id,
                        owner_token=self._owner_token,
                    )
                    if not released:
                        lease_failure = DetectionLeaseFailure(
                            account_id=account.account_id,
                            error_type="LEASE_NOT_OWNED",
                        )
                except Exception as exc:
                    # A failed release leaves a bounded lease that another worker
                    # may take only after expiry; never retry the provider for it.
                    lease_failure = DetectionLeaseFailure(
                        account_id=account.account_id,
                        error_type=type(exc).__name__,
                    )

        return outcome, telemetry_failure, None, lease_failure

    async def run_cycle(self, cycle_id: str) -> DetectionCycleOutcome:
        make_probe_id(cycle_id, "validation")

        outcomes: list[RuntimeExecutionOutcome[MonitoringProbeResult]] = []
        telemetry_failures: list[DetectionTelemetryFailure] = []
        lease_skips: list[DetectionLeaseSkip] = []
        lease_failures: list[DetectionLeaseFailure] = []
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
            for outcome, telemetry_failure, lease_skip, lease_failure in page_results:
                if outcome is not None:
                    outcomes.append(outcome)
                if telemetry_failure is not None:
                    telemetry_failures.append(telemetry_failure)
                if lease_skip is not None:
                    lease_skips.append(lease_skip)
                if lease_failure is not None:
                    lease_failures.append(lease_failure)
            after_account_id = page[-1].account_id
            if len(page) < self._page_size:
                break

        return DetectionCycleOutcome(
            cycle_id=cycle_id,
            outcomes=tuple(outcomes),
            telemetry_failures=tuple(telemetry_failures),
            lease_skips=tuple(lease_skips),
            lease_failures=tuple(lease_failures),
        )
