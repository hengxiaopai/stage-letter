"""D3 PostgreSQL probe; all explicitly-created rows are rolled back."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage_letter.application.services.personal_streamer_profile import PersonalStreamerProfileApplicationService
from stage_letter.infrastructure.db.models import (
    CreatorModel, CreatorProfileModel, FollowModel, PlatformAccountModel, UserCreatorProfileModel, UserModel,
)
from stage_letter.infrastructure.db.repositories.personal_streamer_profile import SQLAlchemyPersonalStreamerProfileRepository

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"


class _ProbeUoW:
    def __init__(self, db: AsyncSession) -> None:
        self.personal_profiles = SQLAlchemyPersonalStreamerProfileRepository(db)
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb: TracebackType | None):
        return False

    async def commit(self) -> None:
        # Flush makes the write queryable while preserving probe rollback.
        await self._db.flush()


async def probe() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    base_id = int(uuid4().hex[:12], 16)
    try:
        async with factory() as db:
            creator = CreatorModel(id=base_id)
            account = PlatformAccountModel(
                id=base_id, creator_id=base_id, platform="douyin",
                platform_user_id=f"d3-{base_id}", canonical_url=f"https://www.douyin.com/user/d3-{base_id}",
                is_disabled=False,
            )
            user_a = UserModel(id=base_id, openid=f"d3-a-{base_id}")
            user_b = UserModel(id=base_id + 1, openid=f"d3-b-{base_id}")
            db.add_all([creator, CreatorProfileModel(creator_id=base_id, display_name="平台旧昵称"), account, user_a, user_b])
            await db.flush()
            db.add_all([
                FollowModel(user_id=user_a.id, creator_id=creator.id, platform_account_id=account.id, starred=False),
                FollowModel(user_id=user_b.id, creator_id=creator.id, platform_account_id=account.id, starred=False),
            ])
            await db.flush()

            service = PersonalStreamerProfileApplicationService(lambda: _ProbeUoW(db))  # type: ignore[arg-type]
            a = await service.patch(
                openid=user_a.openid, creator_id=str(creator.id),
                changes={"user_alias": "A 的称呼", "note": "私密备注", "user_tags": ["A-tag"], "group": "A组"},
            )
            assert a.user_profile is not None and a.user_profile.user_alias == "A 的称呼"
            b = await service.get(openid=user_b.openid, creator_id=str(creator.id))
            assert b.user_profile is None

            # Repeating the same PATCH keeps one (user, creator) record and the same data.
            repeated = await service.patch(
                openid=user_a.openid, creator_id=str(creator.id),
                changes={"user_alias": "A 的称呼", "note": "私密备注", "user_tags": ["A-tag"], "group": "A组"},
            )
            assert repeated.user_profile == a.user_profile
            profile = await db.scalar(
                select(UserCreatorProfileModel).where(
                    UserCreatorProfileModel.user_id == user_a.id,
                    UserCreatorProfileModel.creator_id == creator.id,
                )
            )
            assert profile is not None and profile.user_id == user_a.id and profile.creator_id == creator.id
            await db.rollback()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
    print("D3 PostgreSQL personal streamer profile probe PASS")
