"""Gate 2.4 operational circuit-breaker persistence.

This module maps only the existing physical platform_health table through a
separate SQLAlchemy Core MetaData. It never imports or mutates canonical live
models.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, MetaData, Numeric, String, Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.detection.contracts import PlatformHealthState
from stage_letter.detection.health import CircuitBreakerPolicy, state_after_probe
from stage_letter.detection.telemetry import PlatformHealthSnapshot

SessionFactory = Callable[[], AsyncSession]

_metadata = MetaData()
_platform_health = Table(
    "platform_health",
    _metadata,
    Column("platform", String(32), primary_key=True),
    Column("state", String(16), nullable=False),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_failure_at", DateTime(timezone=True)),
    Column("success_rate_24h", Numeric(5, 2)),
    Column("avg_latency_ms_24h", Integer),
    Column("consecutive_failures", Integer, nullable=False),
    Column("error_count_24h", Integer, nullable=False),
    Column("success_count_24h", Integer, nullable=False),
    Column("sustained_qps", Numeric(6, 2)),
    Column("max_anchors", Integer),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("health transition timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _snapshot(row) -> PlatformHealthSnapshot:
    return PlatformHealthSnapshot(
        platform=str(row["platform"]),
        state=PlatformHealthState(str(row["state"])),
        last_success_at=row["last_success_at"],
        last_failure_at=row["last_failure_at"],
        success_count_24h=int(row["success_count_24h"] or 0),
        error_count_24h=int(row["error_count_24h"] or 0),
        success_rate_24h=(
            None if row["success_rate_24h"] is None else float(row["success_rate_24h"])
        ),
        avg_latency_ms_24h=(
            None if row["avg_latency_ms_24h"] is None else int(row["avg_latency_ms_24h"])
        ),
        consecutive_failures=int(row["consecutive_failures"] or 0),
    )


class SQLAlchemyDetectionHealthRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def _locked_row(self, session: AsyncSession, platform: str):
        if not platform.strip():
            raise ValueError("platform is required")
        return (
            await session.execute(
                select(_platform_health)
                .where(_platform_health.c.platform == platform)
                .with_for_update()
            )
        ).mappings().one_or_none()

    async def apply_probe_outcome(
        self,
        *,
        platform: str,
        success: bool,
        at: datetime,
        policy: CircuitBreakerPolicy,
    ) -> PlatformHealthSnapshot:
        at = _utc(at)
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, platform)
                if row is None:
                    raise ValueError("platform health row must exist after telemetry persistence")
                current = PlatformHealthState(str(row["state"]))
                target = state_after_probe(
                    current=current,
                    success=success,
                    consecutive_failures=int(row["consecutive_failures"] or 0),
                    policy=policy,
                )
                if target is not current:
                    await session.execute(
                        update(_platform_health)
                        .where(_platform_health.c.platform == platform)
                        .values(state=target.value, updated_at=at)
                    )
                refreshed = (
                    await session.execute(
                        select(_platform_health).where(_platform_health.c.platform == platform)
                    )
                ).mappings().one()
        return _snapshot(refreshed)

    async def administrative_disable(
        self,
        *,
        platform: str,
        at: datetime,
    ) -> PlatformHealthSnapshot:
        at = _utc(at)
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, platform)
                if row is None:
                    await session.execute(
                        insert(_platform_health).values(
                            platform=platform,
                            state=PlatformHealthState.DISABLED.value,
                            last_success_at=None,
                            last_failure_at=None,
                            success_rate_24h=None,
                            avg_latency_ms_24h=None,
                            consecutive_failures=0,
                            error_count_24h=0,
                            success_count_24h=0,
                            updated_at=at,
                        )
                    )
                else:
                    await session.execute(
                        update(_platform_health)
                        .where(_platform_health.c.platform == platform)
                        .values(state=PlatformHealthState.DISABLED.value, updated_at=at)
                    )
                refreshed = (
                    await session.execute(
                        select(_platform_health).where(_platform_health.c.platform == platform)
                    )
                ).mappings().one()
        return _snapshot(refreshed)

    async def administrative_enable(
        self,
        *,
        platform: str,
        at: datetime,
    ) -> PlatformHealthSnapshot:
        """Move an administratively disabled platform into a cautious half-open state."""

        at = _utc(at)
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, platform)
                if row is None:
                    await session.execute(
                        insert(_platform_health).values(
                            platform=platform,
                            state=PlatformHealthState.DEGRADED.value,
                            last_success_at=None,
                            last_failure_at=None,
                            success_rate_24h=None,
                            avg_latency_ms_24h=None,
                            consecutive_failures=0,
                            error_count_24h=0,
                            success_count_24h=0,
                            updated_at=at,
                        )
                    )
                else:
                    await session.execute(
                        update(_platform_health)
                        .where(_platform_health.c.platform == platform)
                        .values(
                            state=PlatformHealthState.DEGRADED.value,
                            consecutive_failures=0,
                            updated_at=at,
                        )
                    )
                refreshed = (
                    await session.execute(
                        select(_platform_health).where(_platform_health.c.platform == platform)
                    )
                ).mappings().one()
        return _snapshot(refreshed)
