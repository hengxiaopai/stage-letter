"""Gate 2.5 durable cross-worker detection probe leases.

This is an independent operational SQLAlchemy Core boundary. A lease guards
provider execution for one platform account; it never represents canonical live
truth and is deliberately absent from the frozen Gate 1 ORM Base. Lease timing is
anchored to PostgreSQL time so worker clock skew cannot cause premature takeover.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, delete, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.detection.lease import (
    DetectionLeaseAcquireResult,
    DetectionProbeLease,
)

SessionFactory = Callable[[], AsyncSession]

_metadata = MetaData()
_detection_probe_leases = Table(
    "detection_probe_leases",
    _metadata,
    Column("platform_account_id", BigInteger, primary_key=True),
    Column("probe_id", String(255), nullable=False),
    Column("owner_token", String(64), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("lease_expires_at", DateTime(timezone=True), nullable=False),
)


def _account_pk(account_id: str) -> int:
    try:
        value = int(account_id)
    except ValueError as exc:
        raise ValueError("account_id must be a persistence integer id") from exc
    if value < 1:
        raise ValueError("account_id must be positive")
    return value


class SQLAlchemyDetectionLeaseRepository:
    """Atomically acquire an account lease or take over an expired lease."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def try_acquire(
        self,
        *,
        account_id: str,
        probe_id: str,
        owner_token: str,
        lease_seconds: int,
    ) -> DetectionLeaseAcquireResult:
        account_pk = _account_pk(account_id)
        if not probe_id.startswith("monitor:"):
            raise ValueError("probe_id must use the formal monitor: namespace")
        if not owner_token.strip() or len(owner_token) > 64:
            raise ValueError("owner_token must be 1-64 characters")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

        # lease_seconds is validated as an integer before interpolation. PostgreSQL
        # transaction time is authoritative across every worker/process.
        expires_at = func.now() + text(f"INTERVAL '{lease_seconds} seconds'")
        statement = (
            pg_insert(_detection_probe_leases)
            .values(
                platform_account_id=account_pk,
                probe_id=probe_id,
                owner_token=owner_token,
                acquired_at=func.now(),
                lease_expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=[_detection_probe_leases.c.platform_account_id],
                set_={
                    "probe_id": probe_id,
                    "owner_token": owner_token,
                    "acquired_at": func.now(),
                    "lease_expires_at": expires_at,
                },
                # A live lease is never re-entrant, even for the same owner token.
                # This suppresses duplicate tasks inside one worker as well as
                # overlapping work across independent workers/processes.
                where=_detection_probe_leases.c.lease_expires_at <= func.now(),
            )
            .returning(
                _detection_probe_leases.c.platform_account_id,
                _detection_probe_leases.c.probe_id,
                _detection_probe_leases.c.owner_token,
                _detection_probe_leases.c.acquired_at,
                _detection_probe_leases.c.lease_expires_at,
            )
        )

        async with self._session_factory() as session:
            async with session.begin():
                row = (await session.execute(statement)).mappings().one_or_none()

        if row is None:
            return DetectionLeaseAcquireResult(acquired=False)
        lease = DetectionProbeLease(
            account_id=str(row["platform_account_id"]),
            probe_id=row["probe_id"],
            owner_token=row["owner_token"],
            acquired_at=row["acquired_at"],
            lease_expires_at=row["lease_expires_at"],
        )
        return DetectionLeaseAcquireResult(acquired=True, lease=lease)

    async def release(self, *, account_id: str, owner_token: str) -> bool:
        account_pk = _account_pk(account_id)
        if not owner_token.strip() or len(owner_token) > 64:
            raise ValueError("owner_token must be 1-64 characters")
        statement = (
            delete(_detection_probe_leases)
            .where(
                _detection_probe_leases.c.platform_account_id == account_pk,
                _detection_probe_leases.c.owner_token == owner_token,
            )
            .returning(_detection_probe_leases.c.platform_account_id)
        )
        async with self._session_factory() as session:
            async with session.begin():
                released = (await session.execute(statement)).scalar_one_or_none()
        return released is not None
