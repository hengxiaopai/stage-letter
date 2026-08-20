"""Application service for durable WeChat template state and recovery."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.notification_templates import WeChatTemplateRegistration

UnitOfWorkFactory = Callable[[], UnitOfWork]


class WeChatTemplateRegistryApplicationService:
    """Read template availability and perform explicit administrative recovery."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, template_id: str) -> WeChatTemplateRegistration | None:
        self._validate_template_id(template_id)
        async with self._uow_factory() as uow:
            return await uow.templates.get_wechat_template(template_id)

    async def is_enabled(self, template_id: str) -> bool:
        registration = await self.get(template_id)
        return registration is None or registration.enabled

    async def register(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        self._validate_template_id(template_id)
        async with self._uow_factory() as uow:
            registration = await uow.templates.register_enabled(
                template_id,
                now=now,
            )
            await uow.commit()
            return registration

    async def disable_from_40037(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        self._validate_template_id(template_id)
        async with self._uow_factory() as uow:
            registration = await uow.templates.disable_from_40037(
                template_id,
                now=now,
            )
            await uow.commit()
            return registration

    async def enable_by_administrator(
        self,
        template_id: str,
        *,
        administrator: str,
        now: datetime,
    ) -> WeChatTemplateRegistration:
        self._validate_template_id(template_id)
        if not administrator.strip():
            raise ValueError("administrator is required")
        async with self._uow_factory() as uow:
            registration = await uow.templates.enable_by_administrator(
                template_id,
                administrator=administrator,
                now=now,
            )
            await uow.commit()
            return registration

    @staticmethod
    def _validate_template_id(template_id: str) -> None:
        if not template_id.strip():
            raise ValueError("template_id is required")
