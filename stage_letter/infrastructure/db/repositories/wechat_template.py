"""SQLAlchemy Core repository for Gate 3.2 WeChat template configuration."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.notification_templates import (
    WeChatTemplateRegistration,
    WeChatTemplateState,
    WeChatTemplateStateSource,
)

_TEMPLATE_METADATA = MetaData()
_WECHAT_TEMPLATE_TABLE = Table(
    "wechat_notification_templates",
    _TEMPLATE_METADATA,
    Column("template_id", String(64), primary_key=True),
    Column("state", String(16), nullable=False),
    Column("state_source", String(32), nullable=False),
    Column("updated_by", String(64), nullable=False),
    Column("disabled_reason", String(64)),
    Column("disabled_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class SQLAlchemyWeChatTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_wechat_template(
        self,
        template_id: str,
    ) -> WeChatTemplateRegistration | None:
        result = await self.session.execute(
            select(_WECHAT_TEMPLATE_TABLE).where(
                _WECHAT_TEMPLATE_TABLE.c.template_id == template_id
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else self._to_registration(row)

    async def register_enabled(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        await self.session.execute(
            pg_insert(_WECHAT_TEMPLATE_TABLE)
            .values(
                template_id=template_id,
                state=WeChatTemplateState.ENABLED.value,
                state_source=WeChatTemplateStateSource.REGISTRATION.value,
                updated_by="SYSTEM",
                disabled_reason=None,
                disabled_at=None,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["template_id"])
        )
        registration = await self.get_wechat_template(template_id)
        if registration is None:
            raise RuntimeError("registered template row could not be read")
        return registration

    async def disable_from_40037(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        return await self._set_state(
            template_id,
            state=WeChatTemplateState.DISABLED,
            source=WeChatTemplateStateSource.PROVIDER_40037,
            updated_by="WECHAT_PROVIDER",
            disabled_reason="WECHAT_40037_TEMPLATE_INVALID",
            disabled_at=now,
            now=now,
        )

    async def enable_by_administrator(
        self,
        template_id: str,
        *,
        administrator: str,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        return await self._set_state(
            template_id,
            state=WeChatTemplateState.ENABLED,
            source=WeChatTemplateStateSource.ADMINISTRATOR,
            updated_by=administrator,
            disabled_reason=None,
            disabled_at=None,
            now=now,
        )

    async def _set_state(
        self,
        template_id: str,
        *,
        state: WeChatTemplateState,
        source: WeChatTemplateStateSource,
        updated_by: str,
        disabled_reason: str | None,
        disabled_at: datetime | None,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        statement = (
            pg_insert(_WECHAT_TEMPLATE_TABLE)
            .values(
                template_id=template_id,
                state=state.value,
                state_source=source.value,
                updated_by=updated_by,
                disabled_reason=disabled_reason,
                disabled_at=disabled_at,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["template_id"],
                set_={
                    "state": state.value,
                    "state_source": source.value,
                    "updated_by": updated_by,
                    "disabled_reason": disabled_reason,
                    "disabled_at": disabled_at,
                    "updated_at": now,
                },
            )
            .returning(*_WECHAT_TEMPLATE_TABLE.c)
        )
        row = (await self.session.execute(statement)).mappings().one()
        return self._to_registration(row)

    @staticmethod
    def _to_registration(row) -> WeChatTemplateRegistration:
        return WeChatTemplateRegistration(
            template_id=row["template_id"],
            state=WeChatTemplateState(row["state"]),
            state_source=WeChatTemplateStateSource(row["state_source"]),
            updated_by=row["updated_by"],
            disabled_reason=row["disabled_reason"],
            disabled_at=row["disabled_at"],
            updated_at=row["updated_at"],
        )
