"""User-facing notification history and Mini Program routing contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stage_letter.domain.notifications import DeliveryChannel, DeliveryState


@dataclass(frozen=True)
class AnchorDetailTarget:
    anchor_id: str

    def __post_init__(self) -> None:
        if not self.anchor_id.isdigit() or int(self.anchor_id) < 1:
            raise ValueError("anchor_id must be a positive persistence id")

    @property
    def miniapp_path(self) -> str:
        """Path accepted by WeChat's subscribe-message ``page`` field."""

        return f"pages/detail/index?id={self.anchor_id}"

    @property
    def api_path(self) -> str:
        return f"/api/v1/anchors/{self.anchor_id}"


@dataclass(frozen=True)
class NotificationHistoryEntry:
    delivery_id: int
    user_id: str
    anchor_id: str
    account_id: str
    live_event_id: str
    session_id: str
    display_name: str | None
    avatar_url: str | None
    platform: str
    started_at: datetime
    ended_at: datetime | None
    channel: DeliveryChannel
    state: DeliveryState
    created_at: datetime
    sent_at: datetime | None
    error_code: str | None

    def __post_init__(self) -> None:
        if self.delivery_id < 1:
            raise ValueError("delivery_id must be positive")
        for value, field in (
            (self.user_id, "user_id"),
            (self.anchor_id, "anchor_id"),
            (self.account_id, "account_id"),
            (self.live_event_id, "live_event_id"),
            (self.session_id, "session_id"),
            (self.platform, "platform"),
        ):
            if not value.strip():
                raise ValueError(f"{field} is required")

    @property
    def target(self) -> AnchorDetailTarget:
        return AnchorDetailTarget(self.anchor_id)
