"""Gate 2.5 cross-worker detection lease application service."""
from __future__ import annotations

from stage_letter.detection.lease import (
    DetectionLeaseAcquireResult,
    DetectionLeasePolicy,
)
from stage_letter.detection.ports import DetectionLeaseRepository


class DetectionLeaseApplicationService:
    """Acquire/release short operational provider-execution leases.

    Lease timing is authoritative in PostgreSQL so worker clock skew cannot cause
    premature takeover or accidental extension. The lease suppresses overlapping
    automatic probes while live, but makes no provider exactly-once claim across
    crash/expiry boundaries.
    """

    def __init__(
        self,
        repository: DetectionLeaseRepository,
        *,
        policy: DetectionLeasePolicy | None = None,
    ) -> None:
        self._repository = repository
        self.policy = policy or DetectionLeasePolicy()

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
            lease_seconds=self.policy.lease_seconds,
        )

    async def release(self, *, account_id: str, owner_token: str) -> bool:
        return await self._repository.release(
            account_id=account_id,
            owner_token=owner_token,
        )
