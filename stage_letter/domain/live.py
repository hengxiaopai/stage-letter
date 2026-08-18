"""Canonical live-truth domain types accepted by Gate 0B/0E."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class LiveStatus(str, Enum):
    LIVE = "LIVE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class SessionOrigin(str, Enum):
    TRANSITION = "TRANSITION"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"


class LiveEventType(str, Enum):
    LIVE_STARTED = "LIVE_STARTED"
    LIVE_ENDED = "LIVE_ENDED"


class LiveEventCause(str, Enum):
    TRANSITION = "TRANSITION"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"


@dataclass(frozen=True)
class LiveObservation:
    observation_id: str
    account_id: str
    status: LiveStatus
    observed_at: datetime
    source: str
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.observation_id, "observation_id")
        _required(self.account_id, "account_id")
        _required(self.source, "source")


@dataclass(frozen=True)
class LiveSession:
    session_id: str
    account_id: str
    opened_at: datetime
    origin: SessionOrigin
    closed_at: datetime | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.session_id, "session_id")
        _required(self.account_id, "account_id")
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("closed_at must not be earlier than opened_at")

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True)
class LiveEvent:
    event_id: str
    account_id: str
    session_id: str
    event_type: LiveEventType
    cause: LiveEventCause
    occurred_at: datetime

    def __post_init__(self) -> None:
        _required(self.event_id, "event_id")
        _required(self.account_id, "account_id")
        _required(self.session_id, "session_id")
