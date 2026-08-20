"""Gate 1.6-2 recipient/grant resolution and durable notification enqueue."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.notification_policy import (
    NotificationTarget,
    build_pending_delivery,
    evaluate_notification_eligibility,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    resolve_wechat_grant_state,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class NotificationEnqueueResult:
    event_id: str
    examined: int
    created: int
    reused_existing: int
    skipped_missing_preference: int
    skipped_ineligible: int

    @property
    def wrote_any(self) -> bool:
        return self.created > 0


class NotificationEnqueueApplicationService:
    """Plan and durably enqueue logical deliveries for one canonical event.

    This service consumes only persisted formal truth. It does not call WeChat,
    obtain access tokens, mutate live truth, consume grants, or claim external
    exactly-once delivery. PostgreSQL uniqueness remains the concurrency authority
    for ``(user_id, live_event_id, channel)``.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        batch_size: int = 500,
        channel: DeliveryChannel = DeliveryChannel.WECHAT_SUBSCRIBE,
    ) -> None:
        if batch_size < 1 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._channel = channel

    async def enqueue_live_event(
        self,
        *,
        event_id: str,
        template_id: str,
    ) -> NotificationEnqueueResult:
        if not event_id.strip():
            raise ValueError("event_id is required")
        if not template_id.strip():
            raise ValueError("template_id is required")

        examined = 0
        created = 0
        reused_existing = 0
        skipped_missing_preference = 0
        skipped_ineligible = 0

        async with self._uow_factory() as uow:
            event = await uow.live.get_event(event_id)
            if event is None:
                raise ApplicationNotFoundError(f"live event {event_id!r} not found")

            after_user_id: str | None = None
            while True:
                follows = await uow.follows.list_follows_for_account(
                    event.account_id,
                    created_at_lte=event.occurred_at,
                    after_user_id=after_user_id,
                    limit=self._batch_size,
                )
                if not follows:
                    break

                for follow in follows:
                    examined += 1
                    preference = await uow.follows.get_notification_preference(
                        follow.user_id,
                        event.account_id,
                    )
                    if preference is None:
                        skipped_missing_preference += 1
                        continue

                    ledger = await uow.grants.get_wechat_grant(
                        follow.user_id,
                        template_id,
                    )
                    target = NotificationTarget(
                        user_id=follow.user_id,
                        account_id=event.account_id,
                        following=True,
                        notification_enabled=preference.enabled,
                        grant_state=resolve_wechat_grant_state(ledger),
                    )
                    decision = evaluate_notification_eligibility(
                        event,
                        target,
                        channel=self._channel,
                    )
                    delivery = build_pending_delivery(decision, event, target)
                    if delivery is None:
                        skipped_ineligible += 1
                        continue

                    if await uow.notifications.create_delivery(delivery):
                        created += 1
                    else:
                        reused_existing += 1

                if len(follows) < self._batch_size:
                    break
                after_user_id = follows[-1].user_id

            if created:
                await uow.commit()

        return NotificationEnqueueResult(
            event_id=event_id,
            examined=examined,
            created=created,
            reused_existing=reused_existing,
            skipped_missing_preference=skipped_missing_preference,
            skipped_ineligible=skipped_ineligible,
        )
