"""D2 PostgreSQL acceptance probe; all probe rows are rolled back."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

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

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"


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
            await db.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
    print("D2 PostgreSQL session insights probe PASS")
