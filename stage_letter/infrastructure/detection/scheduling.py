"""Separate operational scheduling persistence for Gate 2 Detection Engine.

This module deliberately does not register operational polling/health columns on
the frozen Gate 1 canonical Base. It reads existing physical columns/tables with
a separate SQLAlchemy Core MetaData boundary.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import BigInteger, Boolean, Column, MetaData, String, Table, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.detection.ports import DetectionScheduleRow
from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.db.models import LiveObservationModel

SessionFactory = Callable[[], AsyncSession]

_detection_metadata = MetaData()
_detection_accounts = Table(
    "platform_accounts",
    _detection_metadata,
    Column("id", BigInteger, primary_key=True),
    Column("creator_id", BigInteger, nullable=False),
    Column("platform", String(32), nullable=False),
    Column("platform_user_id", String(128), nullable=False),
    Column("room_id", String(128)),
    Column("canonical_url", Text),
    Column("is_disabled", Boolean, nullable=False),
    Column("polling_tier", String(16)),
)
_detection_health = Table(
    "platform_health",
    _detection_metadata,
    Column("platform", String(32), primary_key=True),
    Column("state", String(16), nullable=False),
)


class SQLAlchemyDetectionScheduleRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_schedule_rows(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = 100,
    ) -> tuple[DetectionScheduleRow, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        latest_probe = (
            select(
                LiveObservationModel.platform_account_id.label("account_id"),
                func.max(LiveObservationModel.created_at).label("last_probe_at"),
            )
            .where(LiveObservationModel.observation_id.like("monitor:%"))
            .group_by(LiveObservationModel.platform_account_id)
            .subquery()
        )

        statement = (
            select(
                _detection_accounts.c.id,
                _detection_accounts.c.creator_id,
                _detection_accounts.c.platform,
                _detection_accounts.c.platform_user_id,
                _detection_accounts.c.room_id,
                _detection_accounts.c.canonical_url,
                _detection_accounts.c.polling_tier,
                latest_probe.c.last_probe_at,
                _detection_health.c.state.label("platform_health_state"),
            )
            .outerjoin(latest_probe, latest_probe.c.account_id == _detection_accounts.c.id)
            .outerjoin(
                _detection_health,
                _detection_health.c.platform == _detection_accounts.c.platform,
            )
            .where(_detection_accounts.c.is_disabled.is_(False))
            .order_by(_detection_accounts.c.id.asc())
            .limit(limit)
        )
        if after_account_id is not None:
            try:
                after_id = int(after_account_id)
            except ValueError as exc:
                raise ValueError("after_account_id must be a persistence integer id") from exc
            statement = statement.where(_detection_accounts.c.id > after_id)

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).mappings().all()

        return tuple(
            DetectionScheduleRow(
                account=PlatformAccount(
                    account_id=str(row["id"]),
                    creator_id=str(row["creator_id"]),
                    platform=row["platform"],
                    platform_user_id=row["platform_user_id"],
                    room_id=row["room_id"],
                    canonical_url=row["canonical_url"],
                    enabled=True,
                ),
                polling_tier_raw=row["polling_tier"],
                last_probe_at=row["last_probe_at"],
                platform_health_state_raw=row["platform_health_state"],
            )
            for row in rows
        )
