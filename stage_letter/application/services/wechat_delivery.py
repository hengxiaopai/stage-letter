"""Map normalized WeChat outcomes onto the frozen Gate 1.6-3 state machine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
    WeChatNotificationProvider,
)
from stage_letter.application.services.notification_delivery import (
    NotificationDeliveryApplicationService,
)
from stage_letter.domain.notifications import DeliveryState, NotificationDelivery


@dataclass(frozen=True)
class WeChatRetryPolicy:
    base_seconds: float = 10.0
    max_seconds: float = 300.0
    max_attempts: int = 8

    def __post_init__(self) -> None:
        if self.base_seconds <= 0 or self.max_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        return min(self.base_seconds * (2 ** (attempt - 1)), self.max_seconds)


@dataclass(frozen=True)
class WeChatDeliveryAttemptResult:
    delivery: NotificationDelivery
    provider_outcome: ProviderOutcome
    grant_effect: GrantEffect


class WeChatDeliveryAttemptApplicationService:
    """Execute exactly one already-claimed provider attempt.

    Provider I/O happens only after Gate 1.6-3 has durably committed IN_FLIGHT.
    The normalized result is then persisted through the frozen delivery state
    machine. GrantEffect is returned to the caller; Gate 1.6-5 owns real grant
    ledger mutation and runtime wiring.
    """

    def __init__(
        self,
        provider: WeChatNotificationProvider,
        delivery_service: NotificationDeliveryApplicationService,
        *,
        retry_policy: WeChatRetryPolicy | None = None,
    ) -> None:
        if not isinstance(provider, WeChatNotificationProvider):
            raise TypeError("provider must implement WeChatNotificationProvider")
        self._provider = provider
        self._delivery_service = delivery_service
        self._retry_policy = retry_policy or WeChatRetryPolicy()

    async def execute(
        self,
        claimed: NotificationDelivery,
        message: WeChatLiveStartMessage,
        *,
        now: datetime,
    ) -> WeChatDeliveryAttemptResult:
        if claimed.state is not DeliveryState.IN_FLIGHT:
            raise ApplicationInvariantError(
                "WeChat provider execution requires a persisted IN_FLIGHT delivery"
            )
        if claimed.attempt < 1 or claimed.in_flight_at is None:
            raise ApplicationInvariantError(
                "WeChat provider execution requires persisted claim metadata"
            )

        outcome = await self._provider.send(message)
        code = outcome.provider_code
        detail = outcome.provider_message

        if outcome.kind is ProviderOutcomeKind.ACCEPTED:
            updated = await self._delivery_service.mark_sent(claimed.key, now=now)
        elif outcome.kind is ProviderOutcomeKind.AUTH_REQUIRED:
            updated = await self._delivery_service.mark_waiting_auth(
                claimed.key,
                now=now,
                error_code=code,
                error_message=detail,
            )
        elif outcome.kind is ProviderOutcomeKind.CONFIG_BLOCKED:
            updated = await self._delivery_service.mark_blocked_config(
                claimed.key,
                now=now,
                error_code=code,
                error_message=detail,
            )
        elif outcome.kind is ProviderOutcomeKind.RETRYABLE:
            if claimed.attempt >= self._retry_policy.max_attempts:
                updated = await self._delivery_service.mark_failed_terminal(
                    claimed.key,
                    now=now,
                    error_code=(
                        f"RETRY_EXHAUSTED_{code}" if code else "RETRY_EXHAUSTED"
                    ),
                    error_message=detail,
                )
            else:
                updated = await self._delivery_service.schedule_retry(
                    claimed.key,
                    now=now,
                    delay_seconds=self._retry_policy.delay_for_attempt(claimed.attempt),
                    error_code=code,
                    error_message=detail,
                )
        elif outcome.kind is ProviderOutcomeKind.TERMINAL_FAILURE:
            updated = await self._delivery_service.mark_failed_terminal(
                claimed.key,
                now=now,
                error_code=code,
                error_message=detail,
            )
        else:
            updated = await self._delivery_service.mark_ambiguous(
                claimed.key,
                now=now,
                error_code=code or "PROVIDER_OUTCOME_AMBIGUOUS",
                error_message=detail,
            )

        return WeChatDeliveryAttemptResult(
            delivery=updated,
            provider_outcome=outcome,
            grant_effect=outcome.grant_effect,
        )
