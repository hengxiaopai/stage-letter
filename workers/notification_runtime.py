"""Formal multi-channel notification execution runtimes.

This is intentionally separate from the Gate 1.4 live-monitoring composition
freeze. They consume already-enqueued logical deliveries and never mutate live
truth. WeChat provider I/O occurs only after a durable IN_FLIGHT claim; IN_APP
publication is DB-only.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.notification_providers import (
    ProviderOutcome,
    WeChatLiveStartMessage,
    WeChatNotificationProvider,
)
from stage_letter.application.ports import UnitOfWork
from stage_letter.application.services.notification_delivery import (
    DeliveryRecoveryResult,
    NotificationDeliveryApplicationService,
)
from stage_letter.application.services.in_app_delivery import (
    InAppDeliveryApplicationService,
    InAppFallbackApplicationService,
)
from stage_letter.application.services.wechat_finalize import (
    WeChatAtomicDeliveryAttemptApplicationService,
    WeChatDeliveryFinalizationApplicationService,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryState,
    NotificationDelivery,
)
from stage_letter.application.services.wechat_template import (
    WeChatTemplateRegistryApplicationService,
)
from stage_letter.infrastructure.db.models import UserModel


UnitOfWorkFactory = Callable[[], UnitOfWork]
SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class WeChatNotificationRunResult:
    action: str
    delivery: NotificationDelivery | None
    provider_outcome: ProviderOutcome | None = None
    grant_consumed: bool = False
    in_app_fallback: NotificationDelivery | None = None


@dataclass(frozen=True)
class InAppNotificationRunResult:
    action: str
    delivery: NotificationDelivery | None


class InAppNotificationRuntime:
    """Publish at most one due in-app delivery without external provider I/O."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._delivery_service = InAppDeliveryApplicationService(uow_factory)

    async def run_once(self, *, now: datetime) -> InAppNotificationRunResult:
        delivered = await self._delivery_service.deliver_next(now=now)
        if delivered is None:
            return InAppNotificationRunResult("IDLE", None)
        return InAppNotificationRunResult("SENT", delivered)


class WeChatNotificationRuntime:
    """Claim and execute at most one due WeChat delivery per ``run_once`` call."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        session_factory: SessionFactory,
        provider: WeChatNotificationProvider,
        template_id: str,
    ) -> None:
        if not template_id.strip():
            raise ValueError("template_id is required")
        self._uow_factory = uow_factory
        self._session_factory = session_factory
        self._template_id = template_id
        self._delivery_service = NotificationDeliveryApplicationService(
            uow_factory,
            channel=DeliveryChannel.WECHAT_SUBSCRIBE,
        )
        self._fallback_service = InAppFallbackApplicationService(uow_factory)
        self._template_service = WeChatTemplateRegistryApplicationService(uow_factory)
        self._finalizer = WeChatDeliveryFinalizationApplicationService(uow_factory)
        self._attempt_service = WeChatAtomicDeliveryAttemptApplicationService(
            provider,
            self._finalizer,
        )

    async def recover_after_restart(
        self,
        *,
        now: datetime,
        stale_after_seconds: float = 60.0,
        limit: int = 100,
    ) -> DeliveryRecoveryResult:
        return await self._delivery_service.recover_stale_in_flight(
            now=now,
            stale_after_seconds=stale_after_seconds,
            limit=limit,
        )

    async def run_once(self, *, now: datetime) -> WeChatNotificationRunResult:
        claimed = await self._delivery_service.claim_next_due(now=now)
        if claimed is None:
            return WeChatNotificationRunResult("IDLE", None)

        if not await self._template_service.is_enabled(self._template_id):
            updated = await self._delivery_service.mark_blocked_config(
                claimed.key,
                now=now,
                error_code="TEMPLATE_DISABLED",
                error_message="WeChat template is administratively disabled",
            )
            fallback = await self._fallback_service.ensure_for_wechat(updated)
            return WeChatNotificationRunResult(
                "BLOCKED_CONFIG",
                updated,
                in_app_fallback=None if fallback is None else fallback.delivery,
            )

        openid = await self._get_openid(claimed.key.user_id)
        if not openid:
            updated = await self._delivery_service.mark_waiting_auth(
                claimed.key,
                now=now,
                error_code="OPENID_MISSING",
                error_message="WeChat recipient address is unavailable",
            )
            fallback = await self._fallback_service.ensure_for_wechat(updated)
            return WeChatNotificationRunResult(
                "WAITING_AUTH",
                updated,
                in_app_fallback=None if fallback is None else fallback.delivery,
            )

        message = await self._build_message(claimed, openid=openid)
        if message is None:
            updated = await self._delivery_service.mark_failed_terminal(
                claimed.key,
                now=now,
                error_code="DELIVERY_CONTEXT_INVALID",
                error_message="canonical delivery context is missing or inconsistent",
            )
            fallback = await self._fallback_service.ensure_for_wechat(updated)
            return WeChatNotificationRunResult(
                "FAILED_TERMINAL",
                updated,
                in_app_fallback=None if fallback is None else fallback.delivery,
            )

        result = await self._attempt_service.execute(claimed, message, now=now)
        fallback = await self._fallback_service.ensure_for_wechat(result.delivery)
        return WeChatNotificationRunResult(
            action=result.delivery.state.value,
            delivery=result.delivery,
            provider_outcome=result.provider_outcome,
            grant_consumed=result.grant_consumed,
            in_app_fallback=None if fallback is None else fallback.delivery,
        )

    async def _get_openid(self, user_id: str) -> str | None:
        if not user_id.isdigit():
            return None
        async with self._session_factory() as session:
            value = await session.scalar(
                select(UserModel.openid).where(UserModel.id == int(user_id))
            )
        return value if isinstance(value, str) and value.strip() else None

    async def _build_message(
        self,
        claimed: NotificationDelivery,
        *,
        openid: str,
    ) -> WeChatLiveStartMessage | None:
        async with self._uow_factory() as uow:
            event = await uow.live.get_event(claimed.key.live_event_id)
            if event is None:
                return None
            if event.account_id != claimed.account_id or event.session_id != claimed.session_id:
                return None
            account = await uow.creators.get_account(claimed.account_id)
            if account is None:
                return None
            profile = await uow.creators.get_profile(account.creator_id)

        anchor_name = (
            profile.display_name
            if profile is not None and profile.display_name
            else "开场信主播"
        )
        start_time = event.occurred_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M"
        )
        return WeChatLiveStartMessage(
            openid=openid,
            template_id=self._template_id,
            anchor_name=anchor_name,
            room_title=f"{anchor_name}直播间",
            start_time=start_time,
            theme="开播啦",
            activity="点击查看直播",
        )
