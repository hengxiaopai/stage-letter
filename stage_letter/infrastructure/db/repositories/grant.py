"""SQLAlchemy implementation of the formal GrantRepository port."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.notifications import WeChatGrantLedger
from stage_letter.infrastructure.db.models import WeChatSubscriptionGrantModel

from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_wechat_grant(
        self,
        user_id: str,
        template_id: str,
    ) -> WeChatGrantLedger | None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        row = await self.session.scalar(
            select(WeChatSubscriptionGrantModel).where(
                WeChatSubscriptionGrantModel.user_id == user_pk,
                WeChatSubscriptionGrantModel.template_id == template_id,
            )
        )
        if row is None:
            return None
        return WeChatGrantLedger(
            user_id=serialize_persistence_id(row.user_id, field="user_id"),
            template_id=row.template_id,
            granted_count=row.granted_count,
            consumed_count=row.consumed_count,
        )
