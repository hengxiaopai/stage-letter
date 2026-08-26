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
    def statistics_started_at(self) -> datetime:
        """Timestamp used by calendar and statistics boundaries.

        A provider timestamp is allowed to move a session across a calendar
        boundary only when it is explicitly marked as platform sourced.  A
        probe timestamp is transition evidence, not a trusted provider start.
        """
        if self.started_at_source == "platform" and self.source_started_at is not None:
            return self.source_started_at
        return self.opened_at

    @property
    def duration_basis(self) -> str:
        if self.closed_at is None:
            return "UNAVAILABLE"
        if self.started_at_source == "platform" and self.source_started_at is not None:
            return "PLATFORM_START_PROBE_END"
        return "PROBE_START_PROBE_END"

    @property
    def duration_is_estimated(self) -> bool:
        """All D2 durations use a probe-confirmed end, never a provider end."""
        return True

    @property
    def duration_seconds(self) -> int | None:
        if self.closed_at is None:
            return None
        return max(0, int((self.closed_at - self.statistics_started_at).total_seconds()))


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
