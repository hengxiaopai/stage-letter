"""PostgreSQL read model for D2 streamer session insights."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.session_insights import MonitoringAccount, ObservationDay, SessionHistoryRecord
from stage_letter.infrastructure.db.models import LiveObservationModel, LiveSessionModel, PlatformAccountModel

from .identity import parse_persistence_id, serialize_persistence_id

BEIJING = ZoneInfo("Asia/Shanghai")


class SQLAlchemySessionInsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sessions(self, creator_id: str, *, before: tuple[datetime, str] | None = None, limit: int = 21) -> tuple[SessionHistoryRecord, ...]:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        conditions = [PlatformAccountModel.creator_id == creator_pk]
        if before is not None:
            opened_at, session_id = before
            session_pk = parse_persistence_id(session_id, field="session_id")
            conditions.append(or_(LiveSessionModel.opened_at < opened_at, and_(LiveSessionModel.opened_at == opened_at, LiveSessionModel.id < session_pk)))
        rows = (await self.session.execute(
            select(LiveSessionModel, PlatformAccountModel.platform)
            .join(PlatformAccountModel, LiveSessionModel.platform_account_id == PlatformAccountModel.id)
            .where(*conditions)
            .order_by(LiveSessionModel.opened_at.desc(), LiveSessionModel.id.desc())
            .limit(limit)
        )).all()
        return tuple(self._record(row, platform) for row, platform in rows)

    async def list_sessions_in_range(self, creator_id: str, *, start: datetime, end: datetime) -> tuple[SessionHistoryRecord, ...]:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        rows = (await self.session.execute(
            select(LiveSessionModel, PlatformAccountModel.platform)
            .join(PlatformAccountModel, LiveSessionModel.platform_account_id == PlatformAccountModel.id)
            .where(PlatformAccountModel.creator_id == creator_pk, LiveSessionModel.opened_at >= start, LiveSessionModel.opened_at < end)
            .order_by(LiveSessionModel.opened_at.asc(), LiveSessionModel.id.asc())
        )).all()
        return tuple(self._record(row, platform) for row, platform in rows)

    async def list_monitoring_accounts(self, creator_id: str) -> tuple[MonitoringAccount, ...]:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        rows = (await self.session.execute(select(PlatformAccountModel.id, PlatformAccountModel.created_at).where(PlatformAccountModel.creator_id == creator_pk))).all()
        return tuple(MonitoringAccount(serialize_persistence_id(row.id, field="account_id"), row.created_at) for row in rows)

    async def list_observation_days(self, creator_id: str, *, start: datetime, end: datetime) -> tuple[ObservationDay, ...]:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        local_day = func.date(func.timezone("Asia/Shanghai", LiveObservationModel.observed_at))
        rows = (await self.session.execute(
            select(LiveObservationModel.platform_account_id, local_day.label("day"))
            .join(PlatformAccountModel, LiveObservationModel.platform_account_id == PlatformAccountModel.id)
            .where(PlatformAccountModel.creator_id == creator_pk, LiveObservationModel.observed_at >= start, LiveObservationModel.observed_at < end)
            .group_by(LiveObservationModel.platform_account_id, local_day)
        )).all()
        return tuple(ObservationDay(serialize_persistence_id(row.platform_account_id, field="account_id"), row.day) for row in rows)

    @staticmethod
    def _record(row: LiveSessionModel, platform: str) -> SessionHistoryRecord:
        return SessionHistoryRecord(
            session_id=serialize_persistence_id(row.id, field="session_id"),
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            platform=platform, opened_at=row.opened_at, closed_at=row.closed_at,
            source_started_at=row.source_started_at,
            started_at_source=row.started_at_source or "probe", title=row.title,
            cover=row.cover, viewer_count=row.viewer_count,
            provider_room_id=row.provider_room_id,
        )
