from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from stage_letter.application.services.session_insights import SessionInsightsApplicationService
from stage_letter.domain.session_insights import MonitoringAccount, ObservationDay, SessionHistoryRecord

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
BEIJING = ZoneInfo("Asia/Shanghai")


def _row(session_id: str, *, hour: int, closed: bool = True, trusted: bool = True) -> SessionHistoryRecord:
    opened = T0.replace(hour=hour)
    return SessionHistoryRecord(
        session_id=session_id, account_id="40", platform="douyin",
        opened_at=opened, closed_at=opened.replace(hour=hour + 2) if closed else None,
        source_started_at=opened if trusted else None,
        started_at_source="platform" if trusted else "probe",
        title="直播", cover=None, viewer_count=100, provider_room_id="9001",
    )


class _UoW:
    def __init__(self, rows=()) -> None:
        self.session_insights = SimpleNamespace(
            list_sessions=AsyncMock(return_value=rows),
            list_sessions_in_range=AsyncMock(return_value=rows),
            list_monitoring_accounts=AsyncMock(return_value=(MonitoringAccount("40", T0),)),
            list_observation_days=AsyncMock(return_value=(ObservationDay("40", date(2026, 8, 20)),)),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_history_uses_complete_time_and_id_keyset_cursor() -> None:
    rows = (_row("9", hour=12), _row("8", hour=11), _row("7", hour=10))
    first_uow = _UoW(rows)
    service = SessionInsightsApplicationService(lambda: first_uow)  # type: ignore[arg-type]
    page = await service.history("30", limit=2)
    assert [item.session_id for item in page.items] == ["9", "8"]
    assert page.next_cursor

    second_uow = _UoW()
    service = SessionInsightsApplicationService(lambda: second_uow)  # type: ignore[arg-type]
    await service.history("30", limit=2, cursor=page.next_cursor)
    before = second_uow.session_insights.list_sessions.await_args.kwargs["before"]
    assert before == (rows[1].opened_at, "8")


@pytest.mark.asyncio
async def test_statistics_separates_probe_duration_from_trusted_start_analysis() -> None:
    rows = (_row("9", hour=10, trusted=True), _row("8", hour=11, trusted=False), _row("7", hour=12, closed=False, trusted=False))
    service = SessionInsightsApplicationService(lambda: _UoW(rows))  # type: ignore[arg-type]
    result = await service.statistics("30", date(2026, 8, 20), date(2026, 8, 20))
    assert result["session_count"] == 3
    assert result["estimated_duration"]["basis"] == "MIXED"
    assert result["estimated_duration"]["duration_is_estimated"] is True
    assert result["estimated_duration"]["sample_count"] == 2
    assert result["trusted_start_analysis"]["sample_count"] == 1
    assert result["coverage"].basis == "OBSERVED_ACCOUNT_DAYS"


@pytest.mark.asyncio
async def test_calendar_and_stats_use_platform_start_across_beijing_midnight() -> None:
    """A trusted 07-31 23:58 start cannot leak into August from a probe at 00:02."""
    platform_start = datetime(2026, 7, 31, 23, 58, tzinfo=BEIJING)
    opened = datetime(2026, 8, 1, 0, 2, tzinfo=BEIJING)
    boundary = SessionHistoryRecord(
        session_id="99", account_id="40", platform="douyin",
        opened_at=opened.astimezone(timezone.utc),
        closed_at=datetime(2026, 8, 1, 1, 2, tzinfo=BEIJING).astimezone(timezone.utc),
        source_started_at=platform_start.astimezone(timezone.utc), started_at_source="platform",
        title="跨月直播", cover=None, viewer_count=None, provider_room_id="9900",
    )
    uow = _UoW()

    async def sessions_in_range(_creator_id: str, *, start: datetime, end: datetime):
        return tuple(row for row in (boundary,) if start <= row.statistics_started_at < end)

    uow.session_insights.list_sessions_in_range = AsyncMock(side_effect=sessions_in_range)
    service = SessionInsightsApplicationService(lambda: uow)  # type: ignore[arg-type]

    july = await service.calendar("30", "2026-07")
    august = await service.calendar("30", "2026-08")
    july_stats = await service.statistics("30", date(2026, 7, 1), date(2026, 7, 31))
    august_stats = await service.statistics("30", date(2026, 8, 1), date(2026, 8, 31))

    assert july["days"] == [{
        "date": "2026-07-31", "session_count": 1, "completed_session_count": 1,
        "estimated_duration_seconds": 3840,
        "duration_basis": "PLATFORM_START_PROBE_END", "duration_is_estimated": True,
    }]
    assert august["days"] == []
    assert july_stats["session_count"] == 1
    assert august_stats["session_count"] == 0
    assert july_stats["estimated_duration"]["basis"] == "PLATFORM_START_PROBE_END"
    assert july_stats["estimated_duration"]["duration_is_estimated"] is True
    assert august_stats["estimated_duration"]["basis"] == "UNAVAILABLE"


def test_duration_basis_never_claims_a_provider_end() -> None:
    platform = _row("1", hour=10, trusted=True)
    probe = _row("2", hour=11, trusted=False)
    open_session = _row("3", hour=12, closed=False, trusted=True)
    assert platform.duration_basis == "PLATFORM_START_PROBE_END"
    assert probe.duration_basis == "PROBE_START_PROBE_END"
    assert open_session.duration_basis == "UNAVAILABLE"
    assert platform.duration_is_estimated is probe.duration_is_estimated is open_session.duration_is_estimated is True


@pytest.mark.asyncio
async def test_calendar_never_turns_missing_observation_into_offline() -> None:
    uow = _UoW((_row("9", hour=10),))
    uow.session_insights.list_observation_days = AsyncMock(return_value=())
    result = await SessionInsightsApplicationService(lambda: uow).calendar("30", "2026-08")  # type: ignore[arg-type]
    assert result["coverage"].state == "NONE"
    assert "offline" not in str(result).lower()


@pytest.mark.asyncio
async def test_invalid_cursor_and_range_are_rejected() -> None:
    service = SessionInsightsApplicationService(lambda: _UoW())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cursor"):
        await service.history("30", cursor="offset:20")
    with pytest.raises(ValueError, match="YYYY-MM"):
        await service.calendar("30", "2026-13")
    with pytest.raises(ValueError, match="no longer"):
        await service.statistics("30", date(2025, 1, 1), date(2026, 8, 20))


def test_repository_and_migration_are_keyset_and_forward_only() -> None:
    repository = (ROOT / "stage_letter/infrastructure/db/repositories/session_insights.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations/versions/b71f6d2a4c90_d2_session_insight_indexes.py").read_text(encoding="utf-8")
    assert "LiveSessionModel.opened_at < opened_at" in repository
    assert "LiveSessionModel.id < session_pk" in repository
    assert "statistics_started_at = case(" in repository
    assert "LiveSessionModel.source_started_at.is_not(None)" in repository
    assert ".offset(" not in repository
    assert 'down_revision: Union[str, Sequence[str], None] = "a54e8b3c2d61"' in migration
    assert "idx_d2_session_account_cursor" in migration


def test_creator_sequence_is_forward_repaired_after_explicit_identity_imports() -> None:
    migration = (ROOT / "migrations/versions/c82e7a4d1f30_repair_creator_identity_sequence.py").read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "b71f6d2a4c90"' in migration
    assert "pg_get_serial_sequence('creators', 'id')" in migration
    assert "MAX(id) FROM creators" in migration


def test_public_contract_exposes_three_d2_reads_without_mock_data() -> None:
    router = (ROOT / "api/routers/anchors.py").read_text(encoding="utf-8")
    assert '"/anchors/{anchor_id}/sessions"' in router
    assert '"/anchors/{anchor_id}/calendar"' in router
    assert '"/anchors/{anchor_id}/stats"' in router
    assert "mock" not in (ROOT / "stage_letter/application/services/session_insights.py").read_text(encoding="utf-8").lower()
