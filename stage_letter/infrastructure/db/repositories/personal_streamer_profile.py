"""PostgreSQL persistence for D3 user-owned Creator profiles."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.personal_streamer_profile import (
    CreatorPlatformFacts,
    PersonalStreamerProfile,
)
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    CreatorProfileModel,
    FollowModel,
    PlatformAccountModel,
    UserModel,
    UserCreatorProfileModel,
)

from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyPersonalStreamerProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_id_by_openid(self, openid: str) -> str | None:
        row = await self.session.scalar(select(UserModel).where(UserModel.openid == openid))
        return None if row is None else serialize_persistence_id(row.id, field="user_id")

    async def get_creator_facts(self, creator_id: str) -> CreatorPlatformFacts | None:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        if await self.session.get(CreatorModel, creator_pk) is None:
            return None
        profile = await self.session.scalar(
            select(CreatorProfileModel).where(CreatorProfileModel.creator_id == creator_pk)
        )
        accounts = tuple((await self.session.scalars(
            select(PlatformAccountModel)
            .where(PlatformAccountModel.creator_id == creator_pk)
            .order_by(PlatformAccountModel.id.asc())
        )).all())
        return CreatorPlatformFacts(
            creator_id=serialize_persistence_id(creator_pk, field="creator_id"),
            display_name=None if profile is None else profile.display_name,
            avatar_url=None if profile is None else profile.avatar_url,
            bio=None if profile is None else profile.bio,
            platform_accounts=tuple(self._to_account(row) for row in accounts),
        )

    async def has_active_follow(self, user_id: str, creator_id: str) -> bool:
        user_pk = parse_persistence_id(user_id, field="user_id")
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        return bool(await self.session.scalar(
            select(exists().where(
                FollowModel.user_id == user_pk,
                FollowModel.creator_id == creator_pk,
            ))
        ))

    async def get_profile(self, user_id: str, creator_id: str) -> PersonalStreamerProfile | None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        row = await self.session.scalar(
            select(UserCreatorProfileModel).where(
                UserCreatorProfileModel.user_id == user_pk,
                UserCreatorProfileModel.creator_id == creator_pk,
            )
        )
        return None if row is None else self._to_profile(row)

    async def save_profile(self, profile: PersonalStreamerProfile) -> None:
        user_pk = parse_persistence_id(profile.user_id, field="user_id")
        creator_pk = parse_persistence_id(profile.creator_id, field="creator_id")
        row = await self.session.scalar(
            select(UserCreatorProfileModel).where(
                UserCreatorProfileModel.user_id == user_pk,
                UserCreatorProfileModel.creator_id == creator_pk,
            )
        )
        if row is None:
            self.session.add(UserCreatorProfileModel(
                user_id=user_pk, creator_id=creator_pk,
                user_alias=profile.user_alias, note=profile.note,
                group_name=profile.group_name, user_tags=list(profile.user_tags),
                reference_schedule=profile.reference_schedule,
            ))
            return
        row.user_alias = profile.user_alias
        row.note = profile.note
        row.group_name = profile.group_name
        row.user_tags = list(profile.user_tags)
        row.reference_schedule = profile.reference_schedule
        row.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _to_profile(row: UserCreatorProfileModel) -> PersonalStreamerProfile:
        return PersonalStreamerProfile(
            user_id=serialize_persistence_id(row.user_id, field="user_id"),
            creator_id=serialize_persistence_id(row.creator_id, field="creator_id"),
            user_alias=row.user_alias, note=row.note, group_name=row.group_name,
            user_tags=tuple(row.user_tags or ()),
            reference_schedule=row.reference_schedule, updated_at=row.updated_at,
        )

    @staticmethod
    def _to_account(row: PlatformAccountModel) -> PlatformAccount:
        return PlatformAccount(
            account_id=serialize_persistence_id(row.id, field="account_id"),
            creator_id=serialize_persistence_id(row.creator_id, field="creator_id"),
            platform=row.platform, platform_user_id=row.platform_user_id,
            room_id=row.room_id, canonical_url=row.canonical_url,
            enabled=not row.is_disabled,
        )
