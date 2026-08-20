"""Durable notification delivery execution state machine orchestration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from stage_letter.application.errors import ApplicationInvariantError, ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.notifications import (
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    recover_delivery_as_ambiguous,
    schedule_delivery_retry,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class DeliveryRecoveryResult:
    examined: int
    recovered_ambiguous: int


class NotificationDeliveryApplicationService:
    """Own durable claim/retry/recovery transitions, but no provider I/O.

    A claim is committed before any future provider call. If a process later
    restarts with a stale IN_FLIGHT row, recovery moves it to AMBIGUOUS rather
    than blindly resending it. This deliberately provides at-least-once queue
    processing mechanics without claiming external exactly-once delivery.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def claim_next_due(
        self,
        *,
        now: datetime,
        scan_limit: int = 100,
    ) -> NotificationDelivery | None:
        async with self._uow_factory() as uow:
            keys = await uow.notifications.list_due_delivery_keys(
                now,
                limit=scan_limit,
            )
            for key in keys:
                delivery = await uow.notifications.lock_delivery(key)
                if delivery is None:
                    continue
                try:
                    claimed = claim_delivery(delivery, now=now)
                except ValueError:
                    # The candidate can become non-due between the read and the
                    # row lock when another worker wins first. Continue scanning.
                    continue
                await uow.notifications.save_delivery(claimed)
                await uow.commit()
                return claimed
            return None

    async def schedule_retry(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
        delay_seconds: float,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NotificationDelivery:
        async with self._uow_factory() as uow:
            delivery = await self._lock_required(uow, key)
            try:
                updated = schedule_delivery_retry(
                    delivery,
                    now=now,
                    delay_seconds=delay_seconds,
                    error_code=error_code,
                    error_message=error_message,
                )
            except ValueError as exc:
                raise ApplicationInvariantError(str(exc)) from exc
            await uow.notifications.save_delivery(updated)
            await uow.commit()
            return updated

    async def mark_sent(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
    ) -> NotificationDelivery:
        return await self._finish(
            key,
            now=now,
            transition="sent",
        )

    async def mark_waiting_auth(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NotificationDelivery:
        return await self._finish(
            key,
            now=now,
            transition="waiting_auth",
            error_code=error_code,
            error_message=error_message,
        )

    async def mark_blocked_config(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NotificationDelivery:
        return await self._finish(
            key,
            now=now,
            transition="blocked_config",
            error_code=error_code,
            error_message=error_message,
        )

    async def mark_failed_terminal(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NotificationDelivery:
        return await self._finish(
            key,
            now=now,
            transition="failed_terminal",
            error_code=error_code,
            error_message=error_message,
        )

    async def recover_stale_in_flight(
        self,
        *,
        now: datetime,
        stale_after_seconds: float,
        limit: int = 100,
    ) -> DeliveryRecoveryResult:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        stale_before = now - timedelta(seconds=stale_after_seconds)

        async with self._uow_factory() as uow:
            keys = await uow.notifications.list_stale_in_flight_keys(
                stale_before,
                limit=limit,
            )
            recovered = 0
            for key in keys:
                delivery = await uow.notifications.lock_delivery(key)
                if delivery is None:
                    continue
                if (
                    delivery.state is not DeliveryState.IN_FLIGHT
                    or delivery.in_flight_at is None
                    or delivery.in_flight_at > stale_before
                ):
                    continue
                updated = recover_delivery_as_ambiguous(
                    delivery,
                    now=now,
                    error_message="stale IN_FLIGHT observed during crash/restart recovery",
                )
                await uow.notifications.save_delivery(updated)
                recovered += 1

            if recovered:
                await uow.commit()
            return DeliveryRecoveryResult(
                examined=len(keys),
                recovered_ambiguous=recovered,
            )

    async def _finish(
        self,
        key: DeliveryKey,
        *,
        now: datetime,
        transition: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NotificationDelivery:
        transitions = {
            "sent": lambda delivery: mark_delivery_sent(delivery, now=now),
            "waiting_auth": lambda delivery: mark_delivery_waiting_auth(
                delivery,
                now=now,
                error_code=error_code,
                error_message=error_message,
            ),
            "blocked_config": lambda delivery: mark_delivery_blocked_config(
                delivery,
                now=now,
                error_code=error_code,
                error_message=error_message,
            ),
            "failed_terminal": lambda delivery: mark_delivery_failed_terminal(
                delivery,
                now=now,
                error_code=error_code,
                error_message=error_message,
            ),
        }
        transition_fn = transitions[transition]

        async with self._uow_factory() as uow:
            delivery = await self._lock_required(uow, key)
            try:
                updated = transition_fn(delivery)
            except ValueError as exc:
                raise ApplicationInvariantError(str(exc)) from exc
            await uow.notifications.save_delivery(updated)
            await uow.commit()
            return updated

    @staticmethod
    async def _lock_required(
        uow: UnitOfWork,
        key: DeliveryKey,
    ) -> NotificationDelivery:
        delivery = await uow.notifications.lock_delivery(key)
        if delivery is not None:
            return delivery
        existing = await uow.notifications.get_delivery(key)
        if existing is None:
            raise ApplicationNotFoundError(
                "logical notification delivery does not exist"
            )
        raise ApplicationInvariantError(
            "logical notification delivery is currently locked by another worker"
        )
