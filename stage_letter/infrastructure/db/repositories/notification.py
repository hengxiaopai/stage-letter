"""SQLAlchemy implementation of the formal NotificationRepository port."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
)
from stage_letter.infrastructure.db.models import LiveEventModel, NotificationDeliveryModel

from .common import RepositoryMappingError
from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_delivery(self, key: DeliveryKey) -> NotificationDelivery | None:
        event_row = await self._get_event_by_formal_id(key.live_event_id)
        if event_row is None:
            return None
        user_pk = parse_persistence_id(key.user_id, field="user_id")
        row = await self.session.scalar(
            select(NotificationDeliveryModel).where(
                NotificationDeliveryModel.user_id == user_pk,
                NotificationDeliveryModel.live_event_id == event_row.id,
                NotificationDeliveryModel.channel == key.channel.value,
            )
        )
        return None if row is None else self._to_delivery(row, event_row)

    async def create_delivery(self, delivery: NotificationDelivery) -> bool:
        event_row = await self._get_event_by_formal_id(delivery.key.live_event_id)
        if event_row is None:
            raise RepositoryMappingError(
                f"live event {delivery.key.live_event_id!r} does not exist"
            )
        if event_row.live_session_id is None:
            raise RepositoryMappingError(
                f"live event {delivery.key.live_event_id!r} has no live_session_id"
            )

        user_pk = parse_persistence_id(delivery.key.user_id, field="user_id")
        account_pk = parse_persistence_id(delivery.account_id, field="account_id")
        session_pk = parse_persistence_id(delivery.session_id, field="session_id")
        if event_row.platform_account_id != account_pk:
            raise RepositoryMappingError("delivery account_id does not match live event")
        if event_row.live_session_id != session_pk:
            raise RepositoryMappingError("delivery session_id does not match live event")

        statement = (
            pg_insert(NotificationDeliveryModel.__table__)
            .values(
                user_id=user_pk,
                live_event_id=event_row.id,
                live_session_id=session_pk,
                channel=delivery.key.channel.value,
                state=delivery.state.value,
                attempt=0,
                created_at=delivery.created_at,
                updated_at=delivery.created_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_g11_delivery_user_event_channel",
            )
        )
        result = await self.session.execute(statement)
        return bool(result.rowcount)

    async def save_delivery(self, delivery: NotificationDelivery) -> None:
        event_row = await self._get_event_by_formal_id(delivery.key.live_event_id)
        if event_row is None:
            raise RepositoryMappingError(
                f"live event {delivery.key.live_event_id!r} does not exist"
            )
        user_pk = parse_persistence_id(delivery.key.user_id, field="user_id")
        row = await self.session.scalar(
            select(NotificationDeliveryModel).where(
                NotificationDeliveryModel.user_id == user_pk,
                NotificationDeliveryModel.live_event_id == event_row.id,
                NotificationDeliveryModel.channel == delivery.key.channel.value,
            )
        )
        if row is None:
            raise RepositoryMappingError("logical delivery does not exist")
        row.state = delivery.state.value

    async def _get_event_by_formal_id(self, event_id: str) -> LiveEventModel | None:
        return await self.session.scalar(
            select(LiveEventModel).where(LiveEventModel.event_id == event_id)
        )

    @staticmethod
    def _to_delivery(
        row: NotificationDeliveryModel,
        event_row: LiveEventModel,
    ) -> NotificationDelivery:
        if row.live_session_id is None:
            raise RepositoryMappingError(
                f"delivery row {row.id} has no formal live_session_id"
            )
        if event_row.event_id is None:
            raise RepositoryMappingError(
                f"delivery row {row.id} points to legacy event without formal event_id"
            )
        return NotificationDelivery(
            key=DeliveryKey(
                user_id=serialize_persistence_id(row.user_id, field="user_id"),
                live_event_id=event_row.event_id,
                channel=DeliveryChannel(row.channel),
            ),
            account_id=serialize_persistence_id(
                event_row.platform_account_id,
                field="account_id",
            ),
            session_id=serialize_persistence_id(row.live_session_id, field="session_id"),
            created_at=row.created_at,
            state=DeliveryState(row.state),
        )
