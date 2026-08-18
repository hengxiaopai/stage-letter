#!/usr/bin/env python3
"""Gate 0D-1 — notification eligibility and delivery-idempotency truth.

This module is deliberately provider-agnostic. It decides whether a canonical
live event is eligible to enter the WeChat notification delivery pipeline and
creates at most one logical delivery per (user, live_event, channel).

It does not call WeChat APIs and it never mutates creator live state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    WECHAT_SUBSCRIBE = "WECHAT_SUBSCRIBE"


class EventType(str, Enum):
    LIVE_STARTED = "LIVE_STARTED"
    LIVE_ENDED = "LIVE_ENDED"


class EventCause(str, Enum):
    TRANSITION = "TRANSITION"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"


class GrantState(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    WRONG_EVENT_TYPE = "WRONG_EVENT_TYPE"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"
    NOT_FOLLOWING = "NOT_FOLLOWING"
    NOTIFICATION_DISABLED = "NOTIFICATION_DISABLED"
    GRANT_NOT_GRANTED = "GRANT_NOT_GRANTED"


class DeliveryState(str, Enum):
    PENDING = "PENDING"


@dataclass(frozen=True)
class NotificationEvent:
    event_id: str
    account_id: str
    event_type: EventType
    cause: EventCause
    occurred_at: datetime
    session_id: str

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.account_id:
            raise ValueError("account_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")


@dataclass(frozen=True)
class NotificationTarget:
    user_id: str
    account_id: str
    following: bool
    notification_enabled: bool
    grant_state: GrantState

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.account_id:
            raise ValueError("account_id is required")


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: EligibilityReason
    user_id: str
    event_id: str
    channel: Channel


@dataclass(frozen=True)
class DeliveryKey:
    user_id: str
    live_event_id: str
    channel: Channel


@dataclass(frozen=True)
class NotificationDelivery:
    key: DeliveryKey
    account_id: str
    session_id: str
    created_at: datetime
    state: DeliveryState = DeliveryState.PENDING


@dataclass(frozen=True)
class DeliveryCreateResult:
    created: bool
    duplicate: bool
    delivery: NotificationDelivery | None


@dataclass(frozen=True)
class DeliveryLedgerSnapshot:
    deliveries: tuple[NotificationDelivery, ...]


def evaluate_eligibility(
    event: NotificationEvent,
    target: NotificationTarget,
    channel: Channel = Channel.WECHAT_SUBSCRIBE,
) -> EligibilityDecision:
    if target.account_id != event.account_id:
        raise ValueError("target account_id does not match event account_id")

    if event.event_type is not EventType.LIVE_STARTED:
        return EligibilityDecision(False, EligibilityReason.WRONG_EVENT_TYPE, target.user_id, event.event_id, channel)

    if event.cause is EventCause.BOOTSTRAP_LIVE:
        return EligibilityDecision(False, EligibilityReason.BOOTSTRAP_LIVE, target.user_id, event.event_id, channel)

    if not target.following:
        return EligibilityDecision(False, EligibilityReason.NOT_FOLLOWING, target.user_id, event.event_id, channel)

    if not target.notification_enabled:
        return EligibilityDecision(
            False,
            EligibilityReason.NOTIFICATION_DISABLED,
            target.user_id,
            event.event_id,
            channel,
        )

    if target.grant_state is not GrantState.GRANTED:
        return EligibilityDecision(False, EligibilityReason.GRANT_NOT_GRANTED, target.user_id, event.event_id, channel)

    return EligibilityDecision(True, EligibilityReason.ELIGIBLE, target.user_id, event.event_id, channel)


class DeliveryLedger:
    """Logical delivery idempotency boundary.

    Gate 0D-1 intentionally stops before provider sending. A delivery enters the
    ledger only when eligibility is true. Re-evaluating the same user/event/
    channel returns the existing logical delivery rather than creating another.
    """

    def __init__(self) -> None:
        self._deliveries: dict[DeliveryKey, NotificationDelivery] = {}

    def snapshot(self) -> DeliveryLedgerSnapshot:
        return DeliveryLedgerSnapshot(
            deliveries=tuple(
                sorted(
                    self._deliveries.values(),
                    key=lambda item: (
                        item.key.user_id,
                        item.key.live_event_id,
                        item.key.channel.value,
                    ),
                )
            )
        )

    @classmethod
    def from_snapshot(cls, snapshot: DeliveryLedgerSnapshot) -> "DeliveryLedger":
        ledger = cls()
        for delivery in snapshot.deliveries:
            if delivery.key in ledger._deliveries:
                raise ValueError("snapshot contains duplicate delivery key")
            ledger._deliveries[delivery.key] = delivery
        return ledger

    def create_if_eligible(
        self,
        decision: EligibilityDecision,
        event: NotificationEvent,
        target: NotificationTarget,
    ) -> DeliveryCreateResult:
        if decision.user_id != target.user_id or decision.event_id != event.event_id:
            raise ValueError("eligibility decision does not match target/event")
        if target.account_id != event.account_id:
            raise ValueError("target account_id does not match event account_id")

        if not decision.eligible:
            return DeliveryCreateResult(created=False, duplicate=False, delivery=None)

        if decision.reason is not EligibilityReason.ELIGIBLE:
            raise ValueError("eligible decision must use ELIGIBLE reason")

        key = DeliveryKey(
            user_id=target.user_id,
            live_event_id=event.event_id,
            channel=decision.channel,
        )
        existing = self._deliveries.get(key)
        if existing is not None:
            return DeliveryCreateResult(created=False, duplicate=True, delivery=existing)

        delivery = NotificationDelivery(
            key=key,
            account_id=event.account_id,
            session_id=event.session_id,
            created_at=event.occurred_at,
        )
        self._deliveries[key] = delivery
        return DeliveryCreateResult(created=True, duplicate=False, delivery=delivery)

    def get(self, key: DeliveryKey) -> NotificationDelivery | None:
        return self._deliveries.get(key)

    @property
    def count(self) -> int:
        return len(self._deliveries)
