"""D3.1 PostgreSQL concurrency and follow-lifecycle probe.

Every generated row is deleted in ``finally`` so the local development database
is left unchanged after the probe.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.services.personal_streamer_profile import (
    PersonalStreamerProfileApplicationService,
)
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    CreatorProfileModel,
    FollowModel,
    PlatformAccountModel,
    UserCreatorProfileModel,
    UserModel,
)
from stage_letter.infrastructure.db.repositories.personal_streamer_profile import (
    SQLAlchemyPersonalStreamerProfileRepository,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"


class _BarrierProfileRepository(SQLAlchemyPersonalStreamerProfileRepository):
    """Line up two separate transactions immediately before the atomic upsert."""

    def __init__(self, db: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(db)
        self._barrier = barrier

    async def has_active_follow(self, user_id: str, creator_id: str) -> bool:
        result = await super().has_active_follow(user_id, creator_id)
        await self._barrier.wait()
        return result


class _ConcurrentProfileUoW:
    """Minimal real-commit UoW for an intentionally concurrent service call."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], barrier: asyncio.Barrier) -> None:
        self._factory = factory
        self._barrier = barrier
        self._db: AsyncSession | None = None
        self.personal_profiles: _BarrierProfileRepository

    async def __aenter__(self):
        self._db = self._factory()
        self.personal_profiles = _BarrierProfileRepository(self._db, self._barrier)
        return self

    async def __aexit__(self, exc_type, exc, tb: TracebackType | None):
        assert self._db is not None
        if exc_type is not None:
            await self._db.rollback()
        await self._db.close()
        return False

    async def commit(self) -> None:
        assert self._db is not None
        await self._db.commit()


def _service(factory: async_sessionmaker[AsyncSession]) -> PersonalStreamerProfileApplicationService:
    return PersonalStreamerProfileApplicationService(lambda: SQLAlchemyUnitOfWork(factory))


def _concurrent_service(
    factory: async_sessionmaker[AsyncSession], barrier: asyncio.Barrier
) -> PersonalStreamerProfileApplicationService:
    return PersonalStreamerProfileApplicationService(
        lambda: _ConcurrentProfileUoW(factory, barrier)  # type: ignore[arg-type]
    )


async def _profile_count(
    factory: async_sessionmaker[AsyncSession], user_id: int, creator_id: int
) -> int:
    async with factory() as db:
        return int(await db.scalar(
            select(func.count()).select_from(UserCreatorProfileModel).where(
                UserCreatorProfileModel.user_id == user_id,
                UserCreatorProfileModel.creator_id == creator_id,
            )
        ) or 0)


async def _cleanup(factory: async_sessionmaker[AsyncSession], ids: list[int]) -> None:
    async with factory() as db:
        await db.execute(delete(UserCreatorProfileModel).where(UserCreatorProfileModel.user_id.in_(ids)))
        await db.execute(delete(FollowModel).where(FollowModel.user_id.in_(ids)))
        await db.execute(delete(PlatformAccountModel).where(PlatformAccountModel.creator_id.in_(ids)))
        await db.execute(delete(CreatorProfileModel).where(CreatorProfileModel.creator_id.in_(ids)))
        await db.execute(delete(CreatorModel).where(CreatorModel.id.in_(ids)))
        await db.execute(delete(UserModel).where(UserModel.id.in_(ids)))
        await db.commit()


async def probe() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    base_id = int(uuid4().hex[:12], 16)
    creator_a_id, creator_b_id = base_id, base_id + 1
    user_id = base_id + 10
    ids = [creator_a_id, creator_b_id, user_id]
    openid = f"d31-user-{base_id}"
    try:
        async with factory() as db:
            creator_a = CreatorModel(id=creator_a_id)
            creator_b = CreatorModel(id=creator_b_id)
            account_a = PlatformAccountModel(
                id=creator_a_id,
                creator_id=creator_a_id,
                platform="douyin",
                platform_user_id=f"d31-a-{base_id}",
                canonical_url=f"https://www.douyin.com/user/d31-a-{base_id}",
                is_disabled=False,
            )
            account_b = PlatformAccountModel(
                id=creator_b_id,
                creator_id=creator_b_id,
                platform="douyin",
                platform_user_id=f"d31-b-{base_id}",
                canonical_url=f"https://www.douyin.com/user/d31-b-{base_id}",
                is_disabled=False,
            )
            user = UserModel(id=user_id, openid=openid)
            db.add_all([
                creator_a,
                creator_b,
                CreatorProfileModel(creator_id=creator_a_id, display_name="D3.1 Creator A"),
                CreatorProfileModel(creator_id=creator_b_id, display_name="D3.1 Creator B"),
                account_a,
                account_b,
                user,
            ])
            await db.flush()
            db.add_all([
                FollowModel(user_id=user_id, creator_id=creator_a_id, platform_account_id=creator_a_id, starred=False),
                FollowModel(user_id=user_id, creator_id=creator_b_id, platform_account_id=creator_b_id, starred=False),
            ])
            await db.commit()

        # Concurrent first, identical PATCH: one row, neither request gets a 500.
        identical_service = _concurrent_service(factory, asyncio.Barrier(2))
        identical_changes = {"user_alias": "并发称呼", "note": "并发备注", "user_tags": ["D3.1"]}
        first, second = await asyncio.gather(
            identical_service.patch(openid=openid, creator_id=str(creator_a_id), changes=identical_changes),
            identical_service.patch(openid=openid, creator_id=str(creator_a_id), changes=identical_changes),
        )
        assert first.user_profile is not None
        assert second.user_profile is not None
        assert first.user_profile.user_alias == "并发称呼"
        assert second.user_profile.note == "并发备注"
        assert await _profile_count(factory, user_id, creator_a_id) == 1

        # Concurrent field-level PATCH: omitted columns remain at their database value.
        field_service = _concurrent_service(factory, asyncio.Barrier(2))
        await asyncio.gather(
            field_service.patch(openid=openid, creator_id=str(creator_b_id), changes={"user_alias": "只改称呼"}),
            field_service.patch(openid=openid, creator_id=str(creator_b_id), changes={"note": "只改备注"}),
        )
        profile_b = (await _service(factory).get(openid=openid, creator_id=str(creator_b_id))).user_profile
        assert profile_b is not None
        assert profile_b.user_alias == "只改称呼"
        assert profile_b.note == "只改备注"

        # Personal rows survive unfollow, are unavailable while inactive, and restore on re-follow.
        async with factory() as db:
            await db.execute(delete(FollowModel).where(
                FollowModel.user_id == user_id, FollowModel.creator_id == creator_a_id
            ))
            await db.commit()
        service = _service(factory)
        for operation in (
            lambda: service.get(openid=openid, creator_id=str(creator_a_id)),
            lambda: service.patch(openid=openid, creator_id=str(creator_a_id), changes={"note": "不可写"}),
        ):
            try:
                await operation()
            except ApplicationNotFoundError:
                pass
            else:  # pragma: no cover - probe failure branch.
                raise AssertionError("inactive follow unexpectedly exposed a personal profile")
        assert await _profile_count(factory, user_id, creator_a_id) == 1

        async with factory() as db:
            db.add(FollowModel(
                user_id=user_id,
                creator_id=creator_a_id,
                platform_account_id=creator_a_id,
                starred=False,
            ))
            await db.commit()
        restored = (await service.get(openid=openid, creator_id=str(creator_a_id))).user_profile
        assert restored is not None
        assert restored.user_alias == "并发称呼"
        assert restored.note == "并发备注"
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(probe())
    print("D3.1 PostgreSQL concurrent profile probe PASS")
