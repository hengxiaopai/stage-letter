"""Durable Gate 3.1 in-app fallback and delivery services."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
    mark_delivery_sent,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]

_FALLBACK_STATES = frozenset(
    {
        DeliveryState.WAITING_AUTH,
        DeliveryState.BLOCKED_CONFIG,
        DeliveryState.FAILED_TERMINAL,
        DeliveryState.AMBIGUOUS,
    }
)


def requires_in_app_fallback(delivery: NotificationDelivery) -> bool:
    """Return whether a concluded WeChat path requires an internal fallback."""

    return (
        delivery.key.channel is DeliveryChannel.WECHAT_SUBSCRIBE
        and delivery.state in _FALLBACK_STATES
    )


@dataclass(frozen=True)
class InAppFallbackResult:
    delivery: NotificationDelivery
    created: bool


class InAppFallbackApplicationService:
    """Idempotently create a separate IN_APP delivery for a failed WeChat path."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def ensure_for_wechat(
        self,
        source: NotificationDelivery,
    ) -> InAppFallbackResult | None:
        if source.key.channel is not DeliveryChannel.WECHAT_SUBSCRIBE:
            raise ApplicationInvariantError(
                "in-app fallback source must be a WECHAT_SUBSCRIBE delivery"
            )
        if not requires_in_app_fallback(source):
            return None

        fallback = NotificationDelivery(
            key=DeliveryKey(
                user_id=source.key.user_id,
                live_event_id=source.key.live_event_id,
                channel=DeliveryChannel.IN_APP,
            ),
            account_id=source.account_id,
            session_id=source.session_id,
            created_at=source.created_at,
        )
        async with self._uow_factory() as uow:
            created = await uow.notifications.create_delivery(fallback)
            if created:
                await uow.commit()
                return InAppFallbackResult(fallback, True)

            existing = await uow.notifications.get_delivery(fallback.key)
            if existing is None:
                raise ApplicationInvariantError(
                    "in-app fallback conflict did not resolve to an existing delivery"
                )
            return InAppFallbackResult(existing, False)


class InAppDeliveryApplicationService:
    """Atomically publish one due IN_APP delivery without external provider I/O."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def deliver_next(
        self,
        *,
        now: datetime,
        scan_limit: int = 100,
    ) -> NotificationDelivery | None:
        async with self._uow_factory() as uow:
            keys = await uow.notifications.list_due_delivery_keys(
                now,
                limit=scan_limit,
                channel=DeliveryChannel.IN_APP,
            )
            for key in keys:
                delivery = await uow.notifications.lock_delivery(key)
                if delivery is None:
                    continue
                if delivery.key.channel is not DeliveryChannel.IN_APP:
                    raise ApplicationInvariantError(
                        "in-app worker received a non-IN_APP delivery"
                    )
                try:
                    claimed = claim_delivery(delivery, now=now)
                except ValueError:
                    continue
                sent = mark_delivery_sent(claimed, now=now)
                await uow.notifications.save_delivery(sent)
                await uow.commit()
                return sent
            return None
