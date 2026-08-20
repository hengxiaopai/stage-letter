"""Gate 2.5 durable cross-worker probe-lease contracts.

Leases coordinate provider execution only. They are not live truth and do not
provide an exactly-once provider guarantee: a crashed worker may have contacted a
provider before its lease expires and a later worker retries after expiry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DetectionLeasePolicy:
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")


@dataclass(frozen=True)
class DetectionProbeLease:
    account_id: str
    probe_id: str
    owner_token: str
    acquired_at: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id is required")
        if not self.probe_id.startswith("monitor:"):
            raise ValueError("probe_id must use the formal monitor: namespace")
        if not self.owner_token.strip() or len(self.owner_token) > 64:
            raise ValueError("owner_token must be 1-64 characters")
        acquired = _utc(self.acquired_at, field="acquired_at")
        expires = _utc(self.lease_expires_at, field="lease_expires_at")
        if expires <= acquired:
            raise ValueError("lease_expires_at must be after acquired_at")


@dataclass(frozen=True)
class DetectionLeaseAcquireResult:
    acquired: bool
    lease: DetectionProbeLease | None = None

    def __post_init__(self) -> None:
        if self.acquired != (self.lease is not None):
            raise ValueError("acquired must match lease presence")
