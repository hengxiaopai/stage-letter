"""D3 user-owned metadata for a Creator, never platform or live truth."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stage_letter.domain.creators import PlatformAccount


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class PersonalStreamerProfile:
    """Private profile keyed strictly by ``(user_id, creator_id)``."""

    user_id: str
    creator_id: str
    user_alias: str | None = None
    note: str | None = None
    group_name: str | None = None
    user_tags: tuple[str, ...] = ()
    reference_schedule: dict | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.creator_id, "creator_id")


@dataclass(frozen=True)
class CreatorPlatformFacts:
    """Read-only public Creator facts, deliberately separate from D3 metadata."""

    creator_id: str
    display_name: str | None
    avatar_url: str | None
    bio: str | None
    platform_accounts: tuple[PlatformAccount, ...]

    def __post_init__(self) -> None:
        _required(self.creator_id, "creator_id")


@dataclass(frozen=True)
class PersonalStreamerProfileView:
    platform_facts: CreatorPlatformFacts
    user_profile: PersonalStreamerProfile | None
