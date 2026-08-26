"""Read-only contracts for streamer session history and factual insights."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class SessionHistoryRecord:
    session_id: str
    account_id: str
    platform: str
    opened_at: datetime
    closed_at: datetime | None
    source_started_at: datetime | None
    started_at_source: str
    title: str | None
    cover: str | None
    viewer_count: int | None
    provider_room_id: str | None

    @property
    def display_started_at(self) -> datetime:
        return self.source_started_at or self.opened_at

    @property
    def duration_seconds(self) -> int | None:
        if self.closed_at is None:
            return None
        return max(0, int((self.closed_at - self.display_started_at).total_seconds()))


@dataclass(frozen=True)
class MonitoringAccount:
    account_id: str
    created_at: datetime


@dataclass(frozen=True)
class ObservationDay:
    account_id: str
    day: date


@dataclass(frozen=True)
class MonitoringCoverage:
    basis: str
    account_count: int
    observed_account_days: int
    eligible_account_days: int
    ratio: float | None
    state: str
