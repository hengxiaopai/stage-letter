"""SQLAlchemy implementation of the formal GrantRepository port.

The existing ``wechat_subscription_grants`` table is deliberately mapped with a
separate SQLAlchemy Core ``MetaData`` so Gate 1's frozen ten-table formal domain
metadata remains unchanged. Grant/provider truth is consumed through the port;
it is not promoted into the canonical live domain.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.notifications import WeChatGrantLedger

from .identity import parse_persistence_id, serialize_persistence_id


_GRANT_METADATA = MetaData()
_WECHAT_GRANT_TABLE = Table(
    "wechat_subscription_grants",
    _GRANT_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("template_id", String(64), nullable=False),
    Column("granted_count", Integer, nullable=False),
    Column("consumed_count", Integer, nullable=False),
)


class SQLAlchemyGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_wechat_grant(
        self,
        user_id: str,
        template_id: str,
    ) -> WeChatGrantLedger | None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        result = await self.session.execute(
            select(
                _WECHAT_GRANT_TABLE.c.user_id,
                _WECHAT_GRANT_TABLE.c.template_id,
                _WECHAT_GRANT_TABLE.c.granted_count,
                _WECHAT_GRANT_TABLE.c.consumed_count,
            ).where(
                _WECHAT_GRANT_TABLE.c.user_id == user_pk,
                _WECHAT_GRANT_TABLE.c.template_id == template_id,
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return WeChatGrantLedger(
            user_id=serialize_persistence_id(row["user_id"], field="user_id"),
            template_id=row["template_id"],
            granted_count=row["granted_count"],
            consumed_count=row["consumed_count"],
        )
