"""Gate 2.5 cross-worker detection lease application service."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from stage_letter.detection.lease import (
    DetectionLeaseAcquireResult,
    DetectionLeasePolicy,
)
from stage_letter.detection.ports import DetectionLeaseRepository

Clock = Callable[[], datetime]


class DetectionLeaseApplicationService:
    """Acquire/release short operational provider-execution leases.

    The lease only suppresses overlapping automatic probes under a valid lease.
    It does not claim provider exactly-once delivery across crashes or lease expiry.
    """

    def __init__(
        self,
        repository: DetectionLeaseRepository,
        *,
        policy: DetectionLeasePolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self.policy = policy or DetectionLeasePolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("detection lease clock must return timezone-aware timestamps")
        return now

    async def try_acquire(
        self,
        *,
        account_id: str,
        probe_id: str,
        owner_token: str,
    ) -> DetectionLeaseAcquireResult:
        return await self._repository.try_acquire(
            account_id=account_id,
            probe_id=probe_id,
            owner_token=owner_token,
            now=self._now(),
            lease_seconds=self.policy.lease_seconds,
        )

    async def release(self, *, account_id: str, owner_token: str) -> bool:
        return await self._repository.release(
            account_id=account_id,
            owner_token=owner_token,
        )
