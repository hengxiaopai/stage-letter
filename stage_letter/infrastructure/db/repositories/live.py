"""SQLAlchemy implementation of the formal LiveRepository port."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.live import (
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveStatus,
    SessionOrigin,
)
from stage_letter.infrastructure.db.models import (
    LiveEventModel,
    LiveObservationModel,
    LiveSessionModel,
)

from .common import RepositoryMappingError
from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyLiveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_observation(
        self,
        account_id: str,
        source: str,
        observation_id: str,
    ) -> bool:
        account_pk = parse_persistence_id(account_id, field="account_id")
        row_id = await self.session.scalar(
            select(LiveObservationModel.id).where(
                LiveObservationModel.platform_account_id == account_pk,
                LiveObservationModel.source == source,
                LiveObservationModel.observation_id == observation_id,
            )
        )
        return row_id is not None

    async def append_observation(self, observation: LiveObservation) -> None:
        account_pk = parse_persistence_id(observation.account_id, field="account_id")
        statement = (
            pg_insert(LiveObservationModel.__table__)
            .values(
                observation_id=observation.observation_id,
                platform_account_id=account_pk,
                status=observation.status.value,
                observed_at=observation.observed_at,
                source=observation.source,
                source_started_at=observation.source_started_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_live_observation_identity",
            )
        )
        await self.session.execute(statement)

    async def get_latest_observation(self, account_id: str) -> LiveObservation | None:
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(LiveObservationModel)
            .where(LiveObservationModel.platform_account_id == account_pk)
            .order_by(LiveObservationModel.observed_at.desc(), LiveObservationModel.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return LiveObservation(
            observation_id=row.observation_id,
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            status=LiveStatus(row.status),
            observed_at=row.observed_at,
            source=row.source,
            source_started_at=row.source_started_at,
        )

    async def get_open_session(self, account_id: str) -> LiveSession | None:
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(LiveSessionModel).where(
                LiveSessionModel.platform_account_id == account_pk,
                LiveSessionModel.closed_at.is_(None),
            )
        )
        return None if row is None else self._to_session(row)

    async def save_session(self, session: LiveSession) -> None:
        session_pk = parse_persistence_id(session.session_id, field="session_id")
        account_pk = parse_persistence_id(session.account_id, field="account_id")
        row = await self.session.get(LiveSessionModel, session_pk)
        if row is None:
            self.session.add(
                LiveSessionModel(
                    id=session_pk,
                    platform_account_id=account_pk,
                    legacy_anchor_id=None,
                    legacy_platform=None,
                    opened_at=session.opened_at,
                    closed_at=session.closed_at,
                    origin=session.origin.value,
                    source_started_at=session.source_started_at,
                    started_at_source=None,
                    legacy_state=None,
                )
            )
            return
        row.platform_account_id = account_pk
        row.opened_at = session.opened_at
        row.closed_at = session.closed_at
        row.origin = session.origin.value
        row.source_started_at = session.source_started_at

    async def append_event(self, event: LiveEvent) -> None:
        account_pk = parse_persistence_id(event.account_id, field="account_id")
        session_pk = parse_persistence_id(event.session_id, field="session_id")
        statement = (
            pg_insert(LiveEventModel.__table__)
            .values(
                event_id=event.event_id,
                platform_account_id=account_pk,
                live_session_id=session_pk,
                event_type=event.event_type.value,
                cause=event.cause.value,
                occurred_at=event.occurred_at,
            )
            .on_conflict_do_nothing(constraint="uq_g11_live_event_id")
        )
        await self.session.execute(statement)

    async def get_event(self, event_id: str) -> LiveEvent | None:
        row = await self.session.scalar(
            select(LiveEventModel).where(LiveEventModel.event_id == event_id)
        )
        if row is None:
            return None
        if row.live_session_id is None:
            raise RepositoryMappingError(
                f"formal event {event_id!r} has no persisted live_session_id"
            )
        if row.cause is None:
            raise RepositoryMappingError(
                f"formal event {event_id!r} has no persisted cause"
            )
        return LiveEvent(
            event_id=event_id,
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            session_id=serialize_persistence_id(row.live_session_id, field="session_id"),
            event_type=LiveEventType(row.event_type),
            cause=LiveEventCause(row.cause),
            occurred_at=row.occurred_at,
        )

    @staticmethod
    def _to_session(row: LiveSessionModel) -> LiveSession:
        if row.origin is None:
            raise RepositoryMappingError(
                f"legacy session {row.id} has no provable formal origin"
            )
        return LiveSession(
            session_id=serialize_persistence_id(row.id, field="session_id"),
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            opened_at=row.opened_at,
            closed_at=row.closed_at,
            origin=SessionOrigin(row.origin),
            source_started_at=row.source_started_at,
        )
