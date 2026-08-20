"""SQLAlchemy implementation of the formal GrantRepository port.

The existing ``wechat_subscription_grants`` table is deliberately mapped with a
separate SQLAlchemy Core ``MetaData`` so Gate 1's frozen ten-table formal domain
metadata remains unchanged. Grant/provider truth is consumed through the port;
it is not promoted into the canonical live domain.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.notifications import WeChatGrantLedger
from stage_letter.domain.grant_intake import GrantIntakeDecision, WeChatGrantIntake

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
    Column("last_granted_at", DateTime(timezone=True)),
    Column("last_send_at", DateTime(timezone=True)),
    Column("last_send_error", String(255)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

_WECHAT_GRANT_INTAKE_TABLE = Table(
    "wechat_grant_intakes",
    _GRANT_METADATA,
    Column("user_id", BigInteger, primary_key=True),
    Column("request_id", String(64), primary_key=True),
    Column("template_id", String(64), primary_key=True),
    Column("decision", String(16), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
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
                _WECHAT_GRANT_TABLE.c.last_granted_at,
                _WECHAT_GRANT_TABLE.c.last_send_at,
                _WECHAT_GRANT_TABLE.c.last_send_error,
            ).where(
                _WECHAT_GRANT_TABLE.c.user_id == user_pk,
                _WECHAT_GRANT_TABLE.c.template_id == template_id,
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else self._to_ledger(row)

    async def consume_wechat_grant(
        self,
        user_id: str,
        template_id: str,
        *,
        sent_at,
        error_code: str | None = None,
    ) -> WeChatGrantLedger | None:
        """Record one send outcome that authoritatively consumes a grant.

        No availability predicate is used here. Gate 0A established that the
        local ledger is optimistic and provider send results are authoritative;
        therefore consumed_count may legitimately exceed granted_count when the
        local ledger had drifted.
        """

        user_pk = parse_persistence_id(user_id, field="user_id")
        row = (
            await self.session.execute(
                select(
                    _WECHAT_GRANT_TABLE.c.id,
                    _WECHAT_GRANT_TABLE.c.user_id,
                    _WECHAT_GRANT_TABLE.c.template_id,
                    _WECHAT_GRANT_TABLE.c.granted_count,
                    _WECHAT_GRANT_TABLE.c.consumed_count,
                    _WECHAT_GRANT_TABLE.c.last_granted_at,
                )
                .where(
                    _WECHAT_GRANT_TABLE.c.user_id == user_pk,
                    _WECHAT_GRANT_TABLE.c.template_id == template_id,
                )
                .with_for_update()
            )
        ).mappings().one_or_none()
        if row is None:
            return None

        consumed_count = int(row["consumed_count"]) + 1
        await self.session.execute(
            update(_WECHAT_GRANT_TABLE)
            .where(_WECHAT_GRANT_TABLE.c.id == row["id"])
            .values(
                consumed_count=consumed_count,
                last_send_at=sent_at,
                last_send_error=error_code,
                updated_at=sent_at,
            )
        )
        return WeChatGrantLedger(
            user_id=serialize_persistence_id(row["user_id"], field="user_id"),
            template_id=row["template_id"],
            granted_count=int(row["granted_count"]),
            consumed_count=consumed_count,
            last_granted_at=row.get("last_granted_at"),
            last_send_at=sent_at,
            last_send_error=error_code,
        )

    async def create_wechat_grant_intake(
        self,
        intake: WeChatGrantIntake,
    ) -> bool:
        statement = (
            pg_insert(_WECHAT_GRANT_INTAKE_TABLE)
            .values(
                user_id=parse_persistence_id(intake.user_id, field="user_id"),
                request_id=intake.request_id,
                template_id=intake.template_id,
                decision=intake.decision.value,
                received_at=intake.received_at,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "request_id", "template_id"]
            )
        )
        result = await self.session.execute(statement)
        return result.rowcount == 1

    async def get_wechat_grant_intake(
        self,
        user_id: str,
        request_id: str,
        template_id: str,
    ) -> WeChatGrantIntake | None:
        row = (
            await self.session.execute(
                select(_WECHAT_GRANT_INTAKE_TABLE).where(
                    _WECHAT_GRANT_INTAKE_TABLE.c.user_id
                    == parse_persistence_id(user_id, field="user_id"),
                    _WECHAT_GRANT_INTAKE_TABLE.c.request_id == request_id,
                    _WECHAT_GRANT_INTAKE_TABLE.c.template_id == template_id,
                )
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        return WeChatGrantIntake(
            user_id=serialize_persistence_id(row["user_id"], field="user_id"),
            request_id=row["request_id"],
            template_id=row["template_id"],
            decision=GrantIntakeDecision(row["decision"]),
            received_at=row["received_at"],
        )

    async def increment_wechat_grant(
        self,
        user_id: str,
        template_id: str,
        *,
        granted_at,
    ) -> WeChatGrantLedger:
        statement = pg_insert(_WECHAT_GRANT_TABLE).values(
            user_id=parse_persistence_id(user_id, field="user_id"),
            template_id=template_id,
            granted_count=1,
            consumed_count=0,
            last_granted_at=granted_at,
            updated_at=granted_at,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_grant_user_template",
            set_={
                "granted_count": _WECHAT_GRANT_TABLE.c.granted_count + 1,
                "last_granted_at": granted_at,
                "updated_at": granted_at,
            },
        ).returning(
            _WECHAT_GRANT_TABLE.c.user_id,
            _WECHAT_GRANT_TABLE.c.template_id,
            _WECHAT_GRANT_TABLE.c.granted_count,
            _WECHAT_GRANT_TABLE.c.consumed_count,
            _WECHAT_GRANT_TABLE.c.last_granted_at,
            _WECHAT_GRANT_TABLE.c.last_send_at,
            _WECHAT_GRANT_TABLE.c.last_send_error,
        )
        row = (await self.session.execute(statement)).mappings().one()
        return self._to_ledger(row)

    @staticmethod
    def _to_ledger(row) -> WeChatGrantLedger:
        return WeChatGrantLedger(
            user_id=serialize_persistence_id(row["user_id"], field="user_id"),
            template_id=row["template_id"],
            granted_count=int(row["granted_count"]),
            consumed_count=int(row["consumed_count"]),
            last_granted_at=row.get("last_granted_at"),
            last_send_at=row.get("last_send_at"),
            last_send_error=row.get("last_send_error"),
        )
