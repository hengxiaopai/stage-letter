"""Notification truth and logical delivery domain types."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class DeliveryChannel(str, Enum):
    WECHAT_SUBSCRIBE = "WECHAT_SUBSCRIBE"
    IN_APP = "IN_APP"


class GrantState(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True)
class WeChatGrantLedger:
    """Optimistic local ledger for one user's one-time WeChat template grants.

    This ledger is not provider truth. A positive local balance is sufficient to
    plan a WeChat attempt, while zero/negative availability is conservatively
    treated as EXHAUSTED. The ledger never infers DENIED or UNKNOWN.
    """

    user_id: str
    template_id: str
    granted_count: int
    consumed_count: int

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.template_id, "template_id")
        if self.granted_count < 0:
            raise ValueError("granted_count must be non-negative")
        if self.consumed_count < 0:
            raise ValueError("consumed_count must be non-negative")

    @property
    def available(self) -> int:
        return max(0, self.granted_count - self.consumed_count)


def resolve_wechat_grant_state(
    ledger: WeChatGrantLedger | None,
) -> GrantState:
    """Resolve enqueue-time grant truth from the optimistic local ledger only."""

    if ledger is not None and ledger.available > 0:
        return GrantState.GRANTED
    return GrantState.EXHAUSTED


class DeliveryState(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    WAITING_RETRY = "WAITING_RETRY"
    WAITING_AUTH = "WAITING_AUTH"
    BLOCKED_CONFIG = "BLOCKED_CONFIG"
    SENT = "SENT"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class DeliveryKey:
    user_id: str
    live_event_id: str
    channel: DeliveryChannel

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.live_event_id, "live_event_id")


@dataclass(frozen=True)
class NotificationDelivery:
    key: DeliveryKey
    account_id: str
    session_id: str
    created_at: datetime
    state: DeliveryState = DeliveryState.PENDING
    attempt: int = 0
    next_attempt_at: datetime | None = None
    in_flight_at: datetime | None = None
    sent_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        # Gate 1.1 froze state-only value construction for some tests/legacy
        # reads. Gate 1.6-3 therefore keeps the value type tolerant and performs
        # strict execution-metadata validation only when a transition is run.
        _required(self.account_id, "account_id")
        _required(self.session_id, "session_id")
        if self.attempt < 0:
            raise ValueError("attempt must be non-negative")
        if self.error_code is not None and not self.error_code.strip():
            raise ValueError("error_code must not be blank")

    @property
    def is_terminal(self) -> bool:
        return self.state in {DeliveryState.SENT, DeliveryState.FAILED_TERMINAL}

    @property
    def allows_blind_retry(self) -> bool:
        return self.state in {DeliveryState.PENDING, DeliveryState.WAITING_RETRY}

    def is_due(self, now: datetime) -> bool:
        if self.state is DeliveryState.PENDING:
            return True
        return (
            self.state is DeliveryState.WAITING_RETRY
            and self.next_attempt_at is not None
            and self.next_attempt_at <= now
        )


def _require_in_flight_metadata(delivery: NotificationDelivery) -> None:
    if delivery.state is not DeliveryState.IN_FLIGHT:
        raise ValueError("only IN_FLIGHT delivery can resolve an attempt outcome")
    if delivery.attempt < 1 or delivery.in_flight_at is None:
        raise ValueError("IN_FLIGHT transition requires persisted claim metadata")
    if delivery.next_attempt_at is not None or delivery.sent_at is not None:
        raise ValueError("IN_FLIGHT transition has conflicting execution timestamps")


def claim_delivery(delivery: NotificationDelivery, *, now: datetime) -> NotificationDelivery:
    """Claim one due delivery for external work without performing that work."""

    if not delivery.is_due(now):
        raise ValueError(f"delivery in {delivery.state.value} is not due for claim")
    if delivery.state is DeliveryState.PENDING:
        if delivery.attempt != 0 or any(
            (delivery.next_attempt_at, delivery.in_flight_at, delivery.sent_at)
        ):
            raise ValueError("PENDING claim has conflicting execution metadata")
    else:
        if delivery.attempt < 1 or delivery.in_flight_at is not None or delivery.sent_at is not None:
            raise ValueError("WAITING_RETRY claim has conflicting execution metadata")
    return replace(
        delivery,
        state=DeliveryState.IN_FLIGHT,
        attempt=delivery.attempt + 1,
        next_attempt_at=None,
        in_flight_at=now,
        sent_at=None,
        error_code=None,
        error_message=None,
    )


def schedule_delivery_retry(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    delay_seconds: float,
    error_code: str | None = None,
    error_message: str | None = None,
) -> NotificationDelivery:
    """Move a known failed attempt to an explicit future retry time."""

    _require_in_flight_metadata(delivery)
    if delay_seconds <= 0:
        raise ValueError("retry delay_seconds must be positive")
    return replace(
        delivery,
        state=DeliveryState.WAITING_RETRY,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
        in_flight_at=None,
        sent_at=None,
        error_code=error_code,
        error_message=error_message,
    )


def _finish_in_flight(
    delivery: NotificationDelivery,
    *,
    state: DeliveryState,
    now: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
    preserve_in_flight_at: bool = False,
) -> NotificationDelivery:
    _require_in_flight_metadata(delivery)
    return replace(
        delivery,
        state=state,
        next_attempt_at=None,
        in_flight_at=delivery.in_flight_at if preserve_in_flight_at else None,
        sent_at=now if state is DeliveryState.SENT else None,
        error_code=error_code,
        error_message=error_message,
    )


def mark_delivery_sent(
    delivery: NotificationDelivery,
    *,
    now: datetime,
) -> NotificationDelivery:
    return _finish_in_flight(delivery, state=DeliveryState.SENT, now=now)


def mark_delivery_waiting_auth(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
) -> NotificationDelivery:
    return _finish_in_flight(
        delivery,
        state=DeliveryState.WAITING_AUTH,
        now=now,
        error_code=error_code,
        error_message=error_message,
    )


def mark_delivery_blocked_config(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
) -> NotificationDelivery:
    return _finish_in_flight(
        delivery,
        state=DeliveryState.BLOCKED_CONFIG,
        now=now,
        error_code=error_code,
        error_message=error_message,
    )


def mark_delivery_failed_terminal(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
) -> NotificationDelivery:
    return _finish_in_flight(
        delivery,
        state=DeliveryState.FAILED_TERMINAL,
        now=now,
        error_code=error_code,
        error_message=error_message,
    )


def mark_delivery_ambiguous(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    error_code: str = "PROVIDER_OUTCOME_AMBIGUOUS",
    error_message: str | None = None,
) -> NotificationDelivery:
    """Resolve an active attempt whose external side effect cannot be known."""

    return _finish_in_flight(
        delivery,
        state=DeliveryState.AMBIGUOUS,
        now=now,
        error_code=error_code,
        error_message=error_message,
        preserve_in_flight_at=True,
    )


def recover_delivery_as_ambiguous(
    delivery: NotificationDelivery,
    *,
    now: datetime,
    error_code: str = "CRASH_RECOVERY_AMBIGUOUS",
    error_message: str | None = None,
) -> NotificationDelivery:
    """Recover stale IN_FLIGHT conservatively: never put it back on blind retry."""

    return mark_delivery_ambiguous(
        delivery,
        now=now,
        error_code=error_code,
        error_message=error_message,
    )
