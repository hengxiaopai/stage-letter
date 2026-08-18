"""Creator/account identity domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class User:
    user_id: str

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")


@dataclass(frozen=True)
class Creator:
    creator_id: str

    def __post_init__(self) -> None:
        _required(self.creator_id, "creator_id")


@dataclass(frozen=True)
class CreatorProfile:
    creator_id: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.creator_id, "creator_id")


@dataclass(frozen=True)
class PlatformAccount:
    account_id: str
    creator_id: str
    platform: str
    platform_user_id: str
    room_id: str | None = None
    canonical_url: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        _required(self.account_id, "account_id")
        _required(self.creator_id, "creator_id")
        _required(self.platform, "platform")
        _required(self.platform_user_id, "platform_user_id")
