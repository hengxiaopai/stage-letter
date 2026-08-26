"""Gate 5.4 PostgreSQL probe: metadata parity and room-based session split.

This probe never clears shared development tables. All rows are unique to the
probe and the surrounding transaction is rolled back on completion.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.live_session_engine import LiveSessionEngine
from core.models import Anchor, LiveSession, PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus, SessionOrigin
from stage_letter.infrastructure.db.models import CreatorModel
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"
T0 = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)


async def probe() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    token = uuid4().hex
    try:
        async with factory() as db:
            anchor = Anchor(display_name=f"gate54-{token}")
            db.add(anchor)
            await db.flush()
            creator = CreatorModel()
            db.add(creator)
            await db.flush()
            account = PlatformAccount(
                anchor_id=anchor.id,
                creator_id=creator.id,
                platform="bilibili",
                platform_user_id=f"gate54-{token}",
                canonical_url=f"https://live.bilibili.com/{token}",
                last_status="OFFLINE",
            )
            db.add(account)
            await db.flush()

            sessions = LiveSessionEngine(db)
            first = {
                "room_id": "room-1",
                "title": "第一场",
                "cover": "https://cdn.example/one.jpg",
                "viewer_count": "12",
                "source": "bilibili.adapter",
            }
            await sessions.on_probe(account.id, "ONLINE", first, now=T0)
            opened = await sessions.on_probe(account.id, "ONLINE", first, now=T0)
            first_id = opened["session_id"]

            refreshed = dict(first, title="第一场更新", viewer_count="1.8万")
            same_room = await sessions.on_probe(
                account.id, "ONLINE", refreshed, now=T0 + timedelta(seconds=10)
            )
            assert same_room["event"] is None
            first_session = await db.get(LiveSession, first_id)
            assert first_session is not None
            assert first_session.title == "第一场更新"
            assert first_session.viewer_count == 18_000
            assert first_session.provider_room_id == "room-1"
            assert first_session.metadata_source == "bilibili.adapter"

            second = dict(refreshed, room_id="room-2", title="第二场")
            rolled = await sessions.on_probe(
                account.id, "ONLINE", second, now=T0 + timedelta(seconds=20)
            )
            assert rolled["event"] == "CONFIRMED_ONLINE"
            assert rolled["session_id"] != first_id

            first_session = await db.get(LiveSession, first_id)
            second_session = await db.get(LiveSession, rolled["session_id"])
            assert first_session is not None and second_session is not None
            assert first_session.state == "CLOSED"
            assert first_session.ended_at == T0 + timedelta(seconds=20)
            assert second_session.state == "OPEN"
            assert second_session.provider_room_id == "room-2"
            assert second_session.title == "第二场"

            formal_anchor = Anchor(display_name=f"gate54-formal-{token}")
            formal_creator = CreatorModel()
            db.add_all((formal_anchor, formal_creator))
            await db.flush()
            formal_account = PlatformAccount(
                anchor_id=formal_anchor.id,
                creator_id=formal_creator.id,
                platform="douyin",
                platform_user_id=f"gate54-formal-{token}",
                canonical_url=f"https://www.douyin.com/user/{token}",
                last_status="ONLINE",
            )
            db.add(formal_account)
            await db.flush()

            observation = LiveObservation(
                observation_id=f"monitor:gate54:{token}",
                account_id=str(formal_account.id),
                status=LiveStatus.LIVE,
                observed_at=T0,
                source="douyin.streamget.user_live_info",
                room_id="7615000000000000000",
                canonical_url=formal_account.canonical_url,
                title="Formal 直播标题",
                cover="https://cdn.example/formal.jpg",
                viewer_count=321,
            )
            formal_repo = SQLAlchemyLiveRepository(db)
            assert await formal_repo.append_observation(observation)
            persisted_observation = await formal_repo.get_observation(
                observation.account_id, observation.observation_id
            )
            assert persisted_observation == observation
            formal_session = await formal_repo.create_session(
                observation.account_id,
                opened_at=T0,
                origin=SessionOrigin.TRANSITION,
                observation=observation,
            )
            legacy_view = await db.get(LiveSession, int(formal_session.session_id))
            assert legacy_view is not None
            assert legacy_view.anchor_id == formal_anchor.id
            assert legacy_view.platform == "douyin"
            assert legacy_view.state == "OPEN"
            assert legacy_view.title == observation.title
            assert legacy_view.cover == observation.cover
            assert legacy_view.viewer_count == observation.viewer_count
            assert legacy_view.provider_room_id == observation.room_id
            await db.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
    print("Gate 5.4 PostgreSQL probe PASS")
