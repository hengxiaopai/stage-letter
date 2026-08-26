"""Application rules for D2 session history, calendar, and statistics."""
from __future__ import annotations

import base64
import binascii
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.session_insights import MonitoringCoverage, SessionHistoryRecord

UnitOfWorkFactory = Callable[[], UnitOfWork]
BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SessionHistoryPage:
    items: tuple[SessionHistoryRecord, ...]
    next_cursor: str | None


class SessionInsightsApplicationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def history(self, creator_id: str, *, limit: int = 20, cursor: str | None = None) -> SessionHistoryPage:
        self._validate_creator(creator_id)
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        before = self._decode_cursor(cursor) if cursor else None
        async with self._uow_factory() as uow:
            rows = await uow.session_insights.list_sessions(
                creator_id, before=before, limit=limit + 1
            )
        items = rows[:limit]
        next_cursor = self._encode_cursor(items[-1]) if len(rows) > limit else None
        return SessionHistoryPage(items=items, next_cursor=next_cursor)

    async def calendar(self, creator_id: str, month: str) -> dict:
        start, end = self._month_range(month)
        sessions, coverage = await self._range_data(creator_id, start, end)
        grouped: dict[date, list[SessionHistoryRecord]] = defaultdict(list)
        for row in sessions:
            grouped[row.statistics_started_at.astimezone(BEIJING).date()].append(row)
        days = []
        for day in sorted(grouped):
            rows = grouped[day]
            completed = [r for r in rows if r.duration_seconds is not None]
            days.append({
                "date": day.isoformat(),
                "session_count": len(rows),
                "completed_session_count": len(completed),
                "estimated_duration_seconds": sum(r.duration_seconds or 0 for r in completed),
                "duration_basis": self._aggregate_duration_basis(completed),
                "duration_is_estimated": True,
            })
        return {"month": month, "timezone": "Asia/Shanghai", "days": days, "coverage": coverage}

    async def statistics(self, creator_id: str, start_day: date, end_day: date) -> dict:
        if end_day < start_day or (end_day - start_day).days > 366:
            raise ValueError("date range must be ordered and no longer than 367 days")
        start = datetime.combine(start_day, time.min, BEIJING).astimezone(timezone.utc)
        end = datetime.combine(end_day + timedelta(days=1), time.min, BEIJING).astimezone(timezone.utc)
        sessions, coverage = await self._range_data(creator_id, start, end)
        completed = [r for r in sessions if r.duration_seconds is not None]
        durations = [r.duration_seconds or 0 for r in completed]
        trusted = [r for r in sessions if r.source_started_at is not None and r.started_at_source == "platform"]
        hours = Counter(r.source_started_at.astimezone(BEIJING).hour for r in trusted)  # type: ignore[union-attr]
        weekdays = Counter(r.source_started_at.astimezone(BEIJING).weekday() for r in trusted)  # type: ignore[union-attr]
        return {
            "from": start_day.isoformat(), "to": end_day.isoformat(), "timezone": "Asia/Shanghai",
            "streamed_days": len({r.statistics_started_at.astimezone(BEIJING).date() for r in sessions}),
            "session_count": len(sessions), "completed_session_count": len(durations),
            "open_session_count": len(sessions) - len(durations),
            "estimated_duration": {
                "basis": self._aggregate_duration_basis(completed),
                "duration_is_estimated": True,
                "sample_count": len(durations),
                "total_seconds": sum(durations) if durations else None,
                "average_seconds": round(sum(durations) / len(durations)) if durations else None,
                "minimum_seconds": min(durations) if durations else None,
                "maximum_seconds": max(durations) if durations else None,
            },
            "trusted_start_analysis": {
                "basis": "PLATFORM_START_ONLY", "sample_count": len(trusted),
                "hour_distribution": [{"hour": h, "sessions": hours[h]} for h in sorted(hours)],
                "weekday_distribution": [{"weekday": d, "sessions": weekdays[d]} for d in sorted(weekdays)],
            },
            "coverage": coverage,
        }

    async def _range_data(self, creator_id: str, start: datetime, end: datetime) -> tuple[tuple[SessionHistoryRecord, ...], MonitoringCoverage]:
        self._validate_creator(creator_id)
        async with self._uow_factory() as uow:
            sessions = await uow.session_insights.list_sessions_in_range(creator_id, start=start, end=end)
            accounts = await uow.session_insights.list_monitoring_accounts(creator_id)
            observed = await uow.session_insights.list_observation_days(creator_id, start=start, end=end)
        eligible = 0
        today_end = min(end, datetime.now(timezone.utc) + timedelta(days=1))
        for account in accounts:
            account_start = max(start, account.created_at)
            if account_start < today_end:
                eligible += max(1, (today_end.astimezone(BEIJING).date() - account_start.astimezone(BEIJING).date()).days + 1)
        observed_count = len({(row.account_id, row.day) for row in observed})
        ratio = None if eligible == 0 else min(1.0, observed_count / eligible)
        state = "NONE" if observed_count == 0 else ("OBSERVED_DAILY" if ratio == 1.0 else "PARTIAL")
        return sessions, MonitoringCoverage("OBSERVED_ACCOUNT_DAYS", len(accounts), observed_count, eligible, ratio, state)

    @staticmethod
    def _aggregate_duration_basis(rows: list[SessionHistoryRecord]) -> str:
        """Expose a precise basis for homogeneous samples, otherwise MIXED."""
        bases = {row.duration_basis for row in rows}
        if not bases:
            return "UNAVAILABLE"
        return next(iter(bases)) if len(bases) == 1 else "MIXED"

    @staticmethod
    def _validate_creator(value: str) -> None:
        if not value.isdigit() or int(value) < 1:
            raise ValueError("creator_id must be a positive persistence id")

    @staticmethod
    def _month_range(value: str) -> tuple[datetime, datetime]:
        try:
            first = datetime.strptime(value, "%Y-%m").date().replace(day=1)
        except ValueError as exc:
            raise ValueError("month must use YYYY-MM") from exc
        next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (
            datetime.combine(first, time.min, BEIJING).astimezone(timezone.utc),
            datetime.combine(next_month, time.min, BEIJING).astimezone(timezone.utc),
        )

    @staticmethod
    def _encode_cursor(row: SessionHistoryRecord) -> str:
        raw = json.dumps([row.opened_at.isoformat(), row.session_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            opened, session_id = json.loads(raw)
            parsed = datetime.fromisoformat(opened)
            if parsed.tzinfo is None or not str(session_id).isdigit() or int(session_id) < 1:
                raise ValueError
            return parsed, str(session_id)
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("cursor is invalid") from exc
