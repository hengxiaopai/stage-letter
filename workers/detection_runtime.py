"""Gate 2 formal detection-cycle runtime.

Due selection comes from Gate 2.1. Provider execution is delegated to the Gate
2.2 coordinator, while durable provider ingress remains the accepted Gate 1.4
MonitoringProbeApplicationService. No live-state interpretation or notification
work happens here.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.monitoring_probe import (
    MonitoringProbeApplicationService,
    MonitoringProbeRequest,
    MonitoringProbeResult,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    RuntimeExecutionOutcome,
)
from workers.monitoring.scheduler import make_probe_id


@dataclass(frozen=True)
class DetectionCycleOutcome:
    cycle_id: str
    outcomes: tuple[RuntimeExecutionOutcome[MonitoringProbeResult], ...]

    @property
    def succeeded(self) -> bool:
        return all(item.succeeded for item in self.outcomes)


class DetectionCycleRuntime:
    """Run one due-only cycle without bypassing the durable observation ingress."""

    def __init__(
        self,
        targets: DueMonitoringTargetApplicationService,
        probes: MonitoringProbeApplicationService,
        coordinator: DetectionRuntimeCoordinator,
        *,
        page_size: int = 100,
    ) -> None:
        if page_size < 1 or page_size > targets.MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {targets.MAX_PAGE_SIZE}")
        self._targets = targets
        self._probes = probes
        self._coordinator = coordinator
        self._page_size = page_size

    async def _execute_account(
        self,
        *,
        cycle_id: str,
        account: PlatformAccount,
    ) -> RuntimeExecutionOutcome[MonitoringProbeResult]:
        request = MonitoringProbeRequest(
            probe_id=make_probe_id(cycle_id, account.account_id),
            account_id=account.account_id,
        )

        async def operation() -> MonitoringProbeResult:
            return await self._probes.execute(request)

        return await self._coordinator.execute(account.platform, operation)

    async def run_cycle(self, cycle_id: str) -> DetectionCycleOutcome:
        # Validate the stable logical probe namespace before target discovery I/O.
        make_probe_id(cycle_id, "validation")

        outcomes: list[RuntimeExecutionOutcome[MonitoringProbeResult]] = []
        after_account_id: str | None = None
        while True:
            page = await self._targets.list_targets(
                after_account_id=after_account_id,
                limit=self._page_size,
            )
            if not page:
                break

            page_outcomes = await asyncio.gather(
                *(
                    self._execute_account(cycle_id=cycle_id, account=account)
                    for account in page
                )
            )
            outcomes.extend(page_outcomes)
            after_account_id = page[-1].account_id
            if len(page) < self._page_size:
                break

        return DetectionCycleOutcome(cycle_id=cycle_id, outcomes=tuple(outcomes))
