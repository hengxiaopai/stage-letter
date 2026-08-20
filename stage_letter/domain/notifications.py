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

    def __post_init__(self) -> None:
        _required(self.account_id, "account_id")
        _required(self.session_id, "session_id")

    @property
    def is_terminal(self) -> bool:
        return self.state in {DeliveryState.SENT, DeliveryState.FAILED_TERMINAL}

    @property
    def allows_blind_retry(self) -> bool:
        return self.state is not DeliveryState.AMBIGUOUS
