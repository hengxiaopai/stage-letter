"""D2 PostgreSQL acceptance probe; all probe rows are rolled back."""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage_letter.infrastructure.db.models import (
    CreatorModel,
    LiveObservationModel,
    LiveSessionModel,
    PlatformAccountModel,
)
from stage_letter.infrastructure.db.repositories.session_insights import (
    SQLAlchemySessionInsightRepository,
)
from stage_letter.application.services.session_insights import SessionInsightsApplicationService

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"
BEIJING = ZoneInfo("Asia/Shanghai")


class _ProbeUoW:
    """Use the active transaction; the probe rolls it back before exit."""

    def __init__(self, repository: SQLAlchemySessionInsightRepository) -> None:
        self.session_insights = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def probe() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    token = uuid4().hex
    base_id = int(token[:12], 16)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as db:
            creator = CreatorModel(id=base_id)
            db.add(creator)
            await db.flush()
            account = PlatformAccountModel(
                id=base_id,
                creator_id=creator.id, platform="douyin",
                platform_user_id=f"d2-{token}", canonical_url=f"https://www.douyin.com/user/{token}",
                is_disabled=False,
            )
            db.add(account)
            await db.flush()
            for offset in range(3):
                opened = now - timedelta(days=offset, hours=2)
                db.add(LiveSessionModel(
                    id=base_id + offset + 1,
                    platform_account_id=account.id, legacy_anchor_id=None,
                    legacy_platform="douyin", opened_at=opened,
                    closed_at=opened + timedelta(hours=1), origin="TRANSITION",
                    source_started_at=opened, started_at_source="platform",
                    title=f"D2 session {offset}", legacy_state="CLOSED",
                ))
                db.add(LiveObservationModel(
                    id=base_id + offset + 10,
                    observation_id=f"monitor:d2:{token}:{offset}",
                    platform_account_id=account.id, status="LIVE", observed_at=opened,
                    source="d2.acceptance",
                ))
            await db.flush()

            repository = SQLAlchemySessionInsightRepository(db)
            first = await repository.list_sessions(str(creator.id), limit=2)
            assert len(first) == 2
            assert first[0].opened_at > first[1].opened_at
            second = await repository.list_sessions(
                str(creator.id), before=(first[-1].opened_at, first[-1].session_id), limit=2
            )
            assert len(second) == 1
            assert second[0].session_id not in {row.session_id for row in first}

            ranged = await repository.list_sessions_in_range(
                str(creator.id), start=now - timedelta(days=4), end=now + timedelta(days=1)
            )
            observations = await repository.list_observation_days(
                str(creator.id), start=now - timedelta(days=4), end=now + timedelta(days=1)
            )
            assert len(ranged) == 3
            assert len(observations) == 3

            boundary_creator = CreatorModel(id=base_id + 100)
            db.add(boundary_creator)
            await db.flush()
            boundary_account = PlatformAccountModel(
                id=base_id + 100, creator_id=boundary_creator.id, platform="douyin",
                platform_user_id=f"d2-boundary-{token}",
                canonical_url=f"https://www.douyin.com/user/boundary-{token}",
                is_disabled=False,
            )
            db.add(boundary_account)
            await db.flush()
            platform_start = datetime(2026, 7, 31, 23, 58, tzinfo=BEIJING).astimezone(timezone.utc)
            probe_opened = datetime(2026, 8, 1, 0, 2, tzinfo=BEIJING).astimezone(timezone.utc)
            boundary_session = LiveSessionModel(
                id=base_id + 101, platform_account_id=boundary_account.id,
                legacy_anchor_id=None, legacy_platform="douyin", opened_at=probe_opened,
                closed_at=probe_opened + timedelta(hours=1), origin="TRANSITION",
                source_started_at=platform_start, started_at_source="platform",
                title="D2 Beijing month boundary", legacy_state="CLOSED",
            )
            db.add(boundary_session)
            await db.flush()

            july_start = datetime(2026, 7, 1, tzinfo=BEIJING).astimezone(timezone.utc)
            august_start = datetime(2026, 8, 1, tzinfo=BEIJING).astimezone(timezone.utc)
            september_start = datetime(2026, 9, 1, tzinfo=BEIJING).astimezone(timezone.utc)
            assert platform_start == datetime(2026, 7, 31, 15, 58, tzinfo=timezone.utc)
            assert probe_opened == datetime(2026, 7, 31, 16, 2, tzinfo=timezone.utc)
            july_rows = await repository.list_sessions_in_range(
                str(boundary_creator.id), start=july_start, end=august_start
            )
            august_rows = await repository.list_sessions_in_range(
                str(boundary_creator.id), start=august_start, end=september_start
            )
            assert [row.session_id for row in july_rows] == [str(boundary_session.id)]
            assert august_rows == ()

            service = SessionInsightsApplicationService(lambda: _ProbeUoW(repository))  # type: ignore[arg-type]
            july_calendar = await service.calendar(str(boundary_creator.id), "2026-07")
            august_calendar = await service.calendar(str(boundary_creator.id), "2026-08")
            july_stats = await service.statistics(str(boundary_creator.id), date(2026, 7, 1), date(2026, 7, 31))
            august_stats = await service.statistics(str(boundary_creator.id), date(2026, 8, 1), date(2026, 8, 31))
            assert [day["date"] for day in july_calendar["days"]] == ["2026-07-31"]
            assert august_calendar["days"] == []
            assert july_stats["session_count"] == 1
            assert august_stats["session_count"] == 0
            await db.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
    print("D2 PostgreSQL session insights probe PASS")
