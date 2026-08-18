"""User relationship and notification preference domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class Follow:
    user_id: str
    creator_id: str
    account_id: str
    starred: bool = False

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.creator_id, "creator_id")
        _required(self.account_id, "account_id")


@dataclass(frozen=True)
class NotificationPreference:
    user_id: str
    account_id: str
    enabled: bool = True
    silent_start: time | None = None
    silent_end: time | None = None

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.account_id, "account_id")
