"""SQLAlchemy implementation of the formal LiveRepository port."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.ports import ObservationReplayRecord
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
    PlatformAccountModel,
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

    async def get_observation(
        self,
        account_id: str,
        observation_id: str,
    ) -> LiveObservation | None:
        account_pk = parse_persistence_id(account_id, field="account_id")
        rows = (
            await self.session.scalars(
                select(LiveObservationModel)
                .where(
                    LiveObservationModel.platform_account_id == account_pk,
                    LiveObservationModel.observation_id == observation_id,
                )
                .order_by(LiveObservationModel.id.asc())
                .limit(2)
            )
        ).all()
        if not rows:
            return None
        if len(rows) > 1:
            raise RepositoryMappingError(
                "multiple durable observations share one logical probe identity"
            )
        return self._to_observation(rows[0])

    async def append_observation(self, observation: LiveObservation) -> bool:
        account_pk = parse_persistence_id(observation.account_id, field="account_id")
        await self.session.flush()
        statement = (
            pg_insert(LiveObservationModel.__table__)
            .values(
                observation_id=observation.observation_id,
                platform_account_id=account_pk,
                status=observation.status.value,
                observed_at=observation.observed_at,
                source=observation.source,
                source_started_at=observation.source_started_at,
                provenance=self._observation_provenance(observation),
            )
            .on_conflict_do_nothing()
            .returning(LiveObservationModel.id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def list_monitor_observations(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[ObservationReplayRecord, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be >= 0")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        account_pk = parse_persistence_id(account_id, field="account_id")
        rows = (
            await self.session.scalars(
                select(LiveObservationModel)
                .where(
                    LiveObservationModel.platform_account_id == account_pk,
                    LiveObservationModel.observation_id.like("monitor:%"),
                    LiveObservationModel.id > after_sequence,
                )
                .order_by(LiveObservationModel.id.asc())
                .limit(limit)
            )
        ).all()
        return tuple(
            ObservationReplayRecord(
                sequence=row.id,
                observation=self._to_observation(row),
            )
            for row in rows
        )

    async def get_latest_observation(self, account_id: str) -> LiveObservation | None:
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(LiveObservationModel)
            .where(LiveObservationModel.platform_account_id == account_pk)
            .order_by(LiveObservationModel.observed_at.desc(), LiveObservationModel.id.desc())
            .limit(1)
        )
        return None if row is None else self._to_observation(row)

    async def acquire_transition_lock(self, account_id: str) -> None:
        """Acquire a PostgreSQL transaction-scoped advisory lock for one account.

        Canonical account ids are positive BIGINTs. Their negative value is used
        only as an infrastructure lock namespace, keeping the mapping collision-
        free for formal account ids without changing or hashing domain identity.
        PostgreSQL releases this lock automatically at transaction end.
        """

        account_pk = parse_persistence_id(account_id, field="account_id")
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": -account_pk},
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

    async def get_session(self, session_id: str) -> LiveSession | None:
        session_pk = parse_persistence_id(session_id, field="session_id")
        row = await self.session.get(LiveSessionModel, session_pk)
        return None if row is None else self._to_session(row)

    async def create_session(
        self,
        account_id: str,
        *,
        opened_at: datetime,
        origin: SessionOrigin,
        source_started_at: datetime | None = None,
        observation: LiveObservation | None = None,
    ) -> LiveSession:
        """Let PostgreSQL allocate the BIGINT session id; never derive it in app code."""

        account_pk = parse_persistence_id(account_id, field="account_id")
        account = await self.session.get(PlatformAccountModel, account_pk)
        if account is None:
            raise RepositoryMappingError(f"platform account {account_id!r} is missing")
        await self.session.flush()
        metadata = observation if observation is not None else None
        statement = (
            insert(LiveSessionModel.__table__)
            .values(
                platform_account_id=account_pk,
                anchor_id=account.legacy_anchor_id,
                platform=account.platform,
                started_at=opened_at,
                ended_at=None,
                origin=origin.value,
                source_started_at=source_started_at,
                started_at_source=("platform" if source_started_at is not None else "probe"),
                title=None if metadata is None else metadata.title,
                cover=None if metadata is None else metadata.cover,
                viewer_count=None if metadata is None else metadata.viewer_count,
                provider_room_id=None if metadata is None else metadata.room_id,
                metadata_source=None if metadata is None else metadata.source,
                metadata_observed_at=None if metadata is None else metadata.observed_at,
                state="OPEN",
            )
            .returning(LiveSessionModel.id)
        )
        result = await self.session.execute(statement)
        session_pk = result.scalar_one()
        return LiveSession(
            serialize_persistence_id(session_pk, field="session_id"),
            account_id,
            opened_at,
            origin,
            source_started_at=source_started_at,
            title=None if metadata is None else metadata.title,
            cover=None if metadata is None else metadata.cover,
            viewer_count=None if metadata is None else metadata.viewer_count,
            provider_room_id=None if metadata is None else metadata.room_id,
            metadata_source=None if metadata is None else metadata.source,
            metadata_observed_at=None if metadata is None else metadata.observed_at,
        )

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
                    started_at_source=(
                        "platform" if session.source_started_at is not None else "probe"
                    ),
                    title=session.title,
                    cover=session.cover,
                    viewer_count=session.viewer_count,
                    provider_room_id=session.provider_room_id,
                    metadata_source=session.metadata_source,
                    metadata_observed_at=session.metadata_observed_at,
                    legacy_state="CLOSED" if session.closed_at is not None else "OPEN",
                )
            )
            return
        row.platform_account_id = account_pk
        row.opened_at = session.opened_at
        row.closed_at = session.closed_at
        row.origin = session.origin.value
        row.source_started_at = session.source_started_at
        row.title = session.title
        row.cover = session.cover
        row.viewer_count = session.viewer_count
        row.provider_room_id = session.provider_room_id
        row.metadata_source = session.metadata_source
        row.metadata_observed_at = session.metadata_observed_at
        row.legacy_state = "CLOSED" if session.closed_at is not None else "OPEN"

    async def append_event(self, event: LiveEvent) -> bool:
        account_pk = parse_persistence_id(event.account_id, field="account_id")
        session_pk = parse_persistence_id(event.session_id, field="session_id")
        await self.session.flush()
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
            .returning(LiveEventModel.id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

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
    def _to_observation(row: LiveObservationModel) -> LiveObservation:
        provenance = row.provenance or {}
        return LiveObservation(
            observation_id=row.observation_id,
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            status=LiveStatus(row.status),
            observed_at=row.observed_at,
            source=row.source,
            source_started_at=row.source_started_at,
            room_id=provenance.get("room_id"),
            canonical_url=provenance.get("canonical_url"),
            title=provenance.get("title"),
            cover=provenance.get("cover"),
            viewer_count=provenance.get("viewer_count"),
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
            title=row.title,
            cover=row.cover,
            viewer_count=row.viewer_count,
            provider_room_id=row.provider_room_id,
            metadata_source=row.metadata_source,
            metadata_observed_at=row.metadata_observed_at,
        )

    @staticmethod
    def _observation_provenance(observation: LiveObservation) -> dict | None:
        """Persist only normalized, consumer-safe provider facts, never raw payloads."""

        values = {
            "room_id": observation.room_id,
            "canonical_url": observation.canonical_url,
            "title": observation.title,
            "cover": observation.cover,
            "viewer_count": observation.viewer_count,
        }
        compact = {key: value for key, value in values.items() if value is not None}
        return compact or None
