"""Atomic provider-outcome finalization for Gate 1.6-5.

Provider I/O always happens after a durable IN_FLIGHT claim. This module owns the
second transaction: delivery outcome state and provider-authoritative grant
consumption are committed together. If that transaction fails after a real send,
the delivery remains IN_FLIGHT and later restart recovery conservatively moves it
to AMBIGUOUS rather than blindly resending it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from stage_letter.application.errors import ApplicationInvariantError, ApplicationNotFoundError
from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
    WeChatNotificationProvider,
)
from stage_letter.application.ports import UnitOfWork
from stage_letter.application.services.wechat_delivery import WeChatRetryPolicy
from stage_letter.domain.notifications import (
    DeliveryState,
    NotificationDelivery,
    WeChatGrantLedger,
    mark_delivery_ambiguous,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    schedule_delivery_retry,
)
from stage_letter.domain.notification_templates import WeChatTemplateRegistration

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class WeChatAtomicFinalizationResult:
    delivery: NotificationDelivery
    provider_outcome: ProviderOutcome
    grant_ledger: WeChatGrantLedger | None
    grant_consumed: bool
    template_registration: WeChatTemplateRegistration | None = None


class WeChatDeliveryFinalizationApplicationService:
    """Atomically persist one normalized provider outcome plus grant effect."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        retry_policy: WeChatRetryPolicy | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._retry_policy = retry_policy or WeChatRetryPolicy()

    async def finalize(
        self,
        claimed: NotificationDelivery,
        *,
        template_id: str,
        outcome: ProviderOutcome,
        now: datetime,
    ) -> WeChatAtomicFinalizationResult:
        if not template_id.strip():
            raise ValueError("template_id is required")
        self._validate_claim_value(claimed)
        self._validate_grant_effect(outcome)

        async with self._uow_factory() as uow:
            current = await uow.notifications.lock_delivery(claimed.key)
            if current is None:
                existing = await uow.notifications.get_delivery(claimed.key)
                if existing is None:
                    raise ApplicationNotFoundError(
                        "logical notification delivery does not exist"
                    )
                raise ApplicationInvariantError(
                    "logical notification delivery is currently locked by another worker"
                )

            self._validate_current_claim(current, claimed)
            updated = self._apply_outcome(current, outcome, now=now)

            grant_ledger: WeChatGrantLedger | None = None
            grant_consumed = outcome.grant_effect is GrantEffect.CONSUME
            if grant_consumed:
                grant_ledger = await uow.grants.consume_wechat_grant(
                    current.key.user_id,
                    template_id,
                    sent_at=now,
                    error_code=(
                        None
                        if outcome.kind is ProviderOutcomeKind.ACCEPTED
                        else outcome.provider_code
                    ),
                )
                if grant_ledger is None:
                    raise ApplicationInvariantError(
                        "provider-authoritative grant consumption requires an existing ledger"
                    )

            template_registration: WeChatTemplateRegistration | None = None
            if (
                outcome.kind is ProviderOutcomeKind.CONFIG_BLOCKED
                and outcome.provider_code == "40037"
            ):
                template_registration = await uow.templates.disable_from_40037(
                    template_id,
                    now=now,
                )

            await uow.notifications.save_delivery(updated)
            await uow.commit()
            return WeChatAtomicFinalizationResult(
                delivery=updated,
                provider_outcome=outcome,
                grant_ledger=grant_ledger,
                grant_consumed=grant_consumed,
                template_registration=template_registration,
            )

    def _apply_outcome(
        self,
        delivery: NotificationDelivery,
        outcome: ProviderOutcome,
        *,
        now: datetime,
    ) -> NotificationDelivery:
        code = outcome.provider_code
        detail = outcome.provider_message

        if outcome.kind is ProviderOutcomeKind.ACCEPTED:
            return mark_delivery_sent(delivery, now=now)
        if outcome.kind is ProviderOutcomeKind.AUTH_REQUIRED:
            return mark_delivery_waiting_auth(
                delivery,
                now=now,
                error_code=code,
                error_message=detail,
            )
        if outcome.kind is ProviderOutcomeKind.CONFIG_BLOCKED:
            return mark_delivery_blocked_config(
                delivery,
                now=now,
                error_code=code,
                error_message=detail,
            )
        if outcome.kind is ProviderOutcomeKind.RETRYABLE:
            if delivery.attempt >= self._retry_policy.max_attempts:
                return mark_delivery_failed_terminal(
                    delivery,
                    now=now,
                    error_code=(
                        f"RETRY_EXHAUSTED_{code}" if code else "RETRY_EXHAUSTED"
                    ),
                    error_message=detail,
                )
            return schedule_delivery_retry(
                delivery,
                now=now,
                delay_seconds=self._retry_policy.delay_for_attempt(delivery.attempt),
                error_code=code,
                error_message=detail,
            )
        if outcome.kind is ProviderOutcomeKind.TERMINAL_FAILURE:
            return mark_delivery_failed_terminal(
                delivery,
                now=now,
                error_code=code,
                error_message=detail,
            )
        return mark_delivery_ambiguous(
            delivery,
            now=now,
            error_code=code or "PROVIDER_OUTCOME_AMBIGUOUS",
            error_message=detail,
        )

    @staticmethod
    def _validate_claim_value(claimed: NotificationDelivery) -> None:
        if claimed.state is not DeliveryState.IN_FLIGHT:
            raise ApplicationInvariantError(
                "provider finalization requires a persisted IN_FLIGHT delivery"
            )
        if claimed.attempt < 1 or claimed.in_flight_at is None:
            raise ApplicationInvariantError(
                "provider finalization requires persisted claim metadata"
            )

    @staticmethod
    def _validate_current_claim(
        current: NotificationDelivery,
        claimed: NotificationDelivery,
    ) -> None:
        if current.state is not DeliveryState.IN_FLIGHT:
            raise ApplicationInvariantError(
                "provider outcome cannot finalize a non-IN_FLIGHT delivery"
            )
        if (
            current.attempt != claimed.attempt
            or current.in_flight_at != claimed.in_flight_at
            or current.key != claimed.key
        ):
            raise ApplicationInvariantError(
                "provider outcome does not match the currently persisted claim"
            )

    @staticmethod
    def _validate_grant_effect(outcome: ProviderOutcome) -> None:
        should_consume = outcome.kind in {
            ProviderOutcomeKind.ACCEPTED,
            ProviderOutcomeKind.AUTH_REQUIRED,
        }
        if should_consume != (outcome.grant_effect is GrantEffect.CONSUME):
            raise ApplicationInvariantError(
                "provider outcome grant effect conflicts with frozen WeChat semantics"
            )


class WeChatAtomicDeliveryAttemptApplicationService:
    """Perform exactly one real provider call, then atomically finalize its result."""

    def __init__(
        self,
        provider: WeChatNotificationProvider,
        finalizer: WeChatDeliveryFinalizationApplicationService,
    ) -> None:
        if not isinstance(provider, WeChatNotificationProvider):
            raise TypeError("provider must implement WeChatNotificationProvider")
        self._provider = provider
        self._finalizer = finalizer

    async def execute(
        self,
        claimed: NotificationDelivery,
        message: WeChatLiveStartMessage,
        *,
        now: datetime,
    ) -> WeChatAtomicFinalizationResult:
        WeChatDeliveryFinalizationApplicationService._validate_claim_value(claimed)
        outcome = await self._provider.send(message)
        return await self._finalizer.finalize(
            claimed,
            template_id=message.template_id,
            outcome=outcome,
            now=now,
        )
