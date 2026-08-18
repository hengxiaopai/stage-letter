"""Notification truth and logical delivery domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class DeliveryChannel(str, Enum):
    WECHAT_SUBSCRIBE = "WECHAT_SUBSCRIBE"


class GrantState(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


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

    def __post_init__(self) -> None:
        _required(self.account_id, "account_id")
        _required(self.session_id, "session_id")

    @property
    def is_terminal(self) -> bool:
        return self.state in {DeliveryState.SENT, DeliveryState.FAILED_TERMINAL}

    @property
    def allows_blind_retry(self) -> bool:
        return self.state is not DeliveryState.AMBIGUOUS
