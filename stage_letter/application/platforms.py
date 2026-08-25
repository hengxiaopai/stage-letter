"""Infrastructure-free platform adapter contracts for Gate 1.3.

Adapters translate provider-specific responses into normalized facts. They do
not mutate canonical live truth, own persistence transactions, or expose legacy
provider status vocabularies inward.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class ResolvedCreator:
    """Provider identity resolved from user input, before internal ids exist."""

    platform: str
    platform_user_id: str
    display_name: str | None = None
    room_id: str | None = None
    canonical_url: str | None = None

    def __post_init__(self) -> None:
        _required(self.platform, "platform")
        _required(self.platform_user_id, "platform_user_id")


@dataclass(frozen=True)
class CreatorProfileSnapshot:
    """Normalized provider profile facts for one external account identity."""

    platform: str
    platform_user_id: str
    observed_at: datetime
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None

    def __post_init__(self) -> None:
        _required(self.platform, "platform")
        _required(self.platform_user_id, "platform_user_id")


@dataclass(frozen=True)
class LiveSnapshot:
    """Normalized provider live-state fact.

    The formal status boundary is intentionally limited to LIVE/OFFLINE/UNKNOWN.
    Transport failures, parse failures, rate limits, auth challenges, missing
    fields, and other ambiguous provider outcomes must reach this boundary as
    UNKNOWN rather than being coerced to OFFLINE.
    """

    platform: str
    platform_user_id: str
    status: LiveStatus
    observed_at: datetime
    source: str
    source_started_at: datetime | None = None
    room_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    cover: str | None = None
    viewer_count: int | None = None

    def __post_init__(self) -> None:
        _required(self.platform, "platform")
        _required(self.platform_user_id, "platform_user_id")
        _required(self.source, "source")
        if self.room_id is not None and not self.room_id.strip():
            raise ValueError("room_id must be non-empty when present")
        if self.viewer_count is not None:
            if isinstance(self.viewer_count, bool) or not isinstance(self.viewer_count, int):
                raise ValueError("viewer_count must be an integer when present")
            if self.viewer_count < 0:
                raise ValueError("viewer_count must be non-negative")


@runtime_checkable
class LivePlatformAdapter(Protocol):
    """Formal async adapter boundary implemented by infrastructure providers."""

    async def resolve_creator(self, input: str) -> ResolvedCreator: ...

    async def get_creator_profile(
        self,
        account: PlatformAccount,
    ) -> CreatorProfileSnapshot: ...

    async def get_live_snapshot(self, account: PlatformAccount) -> LiveSnapshot: ...
