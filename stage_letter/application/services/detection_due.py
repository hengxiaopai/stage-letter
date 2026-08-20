"""Gate 2 due-target selection for formal monitoring."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from stage_letter.detection.due import DetectionCadencePolicy, is_due, normalize_polling_tier
from stage_letter.detection.health import (
    CircuitBreakerPolicy,
    cadence_multiplier,
    normalize_platform_health_state,
)
from stage_letter.detection.ports import DetectionScheduleRepository
from stage_letter.domain.creators import PlatformAccount

Clock = Callable[[], datetime]


class DueMonitoringTargetApplicationService:
    """Return only enabled accounts whose operational cadence is due.

    The public paging shape intentionally matches Gate 1's monitoring-target
    service so the accepted MonitoringScheduler can be reused unchanged. Gate
    2.4 additionally applies platform health: DEGRADED slows cadence and DISABLED
    removes the platform from automatic discovery.
    """

    MAX_PAGE_SIZE = 1000
    DEFAULT_PAGE_SIZE = 100

    def __init__(
        self,
        repository: DetectionScheduleRepository,
        *,
        cadence: DetectionCadencePolicy | None = None,
        circuit_breaker: CircuitBreakerPolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self.cadence = cadence or DetectionCadencePolicy()
        self.circuit_breaker = circuit_breaker or CircuitBreakerPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def list_targets(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[PlatformAccount, ...]:
        if limit < 1 or limit > self.MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {self.MAX_PAGE_SIZE}")

        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("detection clock must return timezone-aware timestamps")

        selected: list[PlatformAccount] = []
        cursor = after_account_id
        scan_size = self.MAX_PAGE_SIZE

        while len(selected) < limit:
            rows = await self._repository.list_schedule_rows(
                after_account_id=cursor,
                limit=scan_size,
            )
            if not rows:
                break

            for row in rows:
                cursor = row.account.account_id
                if not row.account.enabled:
                    continue
                health_state = normalize_platform_health_state(row.platform_health_state_raw)
                multiplier = cadence_multiplier(health_state, policy=self.circuit_breaker)
                if multiplier is None:
                    continue
                tier = normalize_polling_tier(row.polling_tier_raw)
                if is_due(
                    now=now,
                    tier=tier,
                    last_probe_at=row.last_probe_at,
                    policy=self.cadence,
                    interval_multiplier=multiplier,
                ):
                    selected.append(row.account)
                    if len(selected) >= limit:
                        break

            if len(rows) < scan_size:
                break

        return tuple(selected)
