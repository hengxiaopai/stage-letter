"""SQLAlchemy implementation of the formal CreatorRepository port."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    CreatorProfileModel,
    PlatformAccountModel,
)

from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyCreatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_creator(self, creator_id: str) -> Creator | None:
        row = await self.session.get(
            CreatorModel,
            parse_persistence_id(creator_id, field="creator_id"),
        )
        return None if row is None else Creator(creator_id=serialize_persistence_id(row.id, field="creator_id"))

    async def get_profile(self, creator_id: str) -> CreatorProfile | None:
        creator_pk = parse_persistence_id(creator_id, field="creator_id")
        row = await self.session.scalar(
            select(CreatorProfileModel).where(CreatorProfileModel.creator_id == creator_pk)
        )
        if row is None:
            return None
        return CreatorProfile(
            creator_id=serialize_persistence_id(row.creator_id, field="creator_id"),
            display_name=row.display_name,
            avatar_url=row.avatar_url,
            bio=row.bio,
            verified_at=row.verified_at,
        )

    async def get_account(self, account_id: str) -> PlatformAccount | None:
        row = await self.session.get(
            PlatformAccountModel,
            parse_persistence_id(account_id, field="account_id"),
        )
        return None if row is None else self._to_account(row)

    async def get_account_by_platform_identity(
        self,
        platform: str,
        platform_user_id: str,
    ) -> PlatformAccount | None:
        row = await self.session.scalar(
            select(PlatformAccountModel).where(
                PlatformAccountModel.platform == platform,
                PlatformAccountModel.platform_user_id == platform_user_id,
            )
        )
        return None if row is None else self._to_account(row)

    async def list_enabled_accounts(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformAccount, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        statement = select(PlatformAccountModel).where(
            PlatformAccountModel.is_disabled.is_(False)
        )
        if after_account_id is not None:
            after_pk = parse_persistence_id(after_account_id, field="account_id")
            statement = statement.where(PlatformAccountModel.id > after_pk)

        rows = (
            await self.session.scalars(
                statement.order_by(PlatformAccountModel.id.asc()).limit(limit)
            )
        ).all()
        return tuple(self._to_account(row) for row in rows)

    async def save_creator(self, creator: Creator) -> None:
        creator_pk = parse_persistence_id(creator.creator_id, field="creator_id")
        if await self.session.get(CreatorModel, creator_pk) is None:
            self.session.add(CreatorModel(id=creator_pk))

    async def save_profile(self, profile: CreatorProfile) -> None:
        creator_pk = parse_persistence_id(profile.creator_id, field="creator_id")
        row = await self.session.scalar(
            select(CreatorProfileModel).where(CreatorProfileModel.creator_id == creator_pk)
        )
        if row is None:
            self.session.add(
                CreatorProfileModel(
                    creator_id=creator_pk,
                    display_name=profile.display_name,
                    avatar_url=profile.avatar_url,
                    bio=profile.bio,
                    verified_at=profile.verified_at,
                )
            )
            return
        row.display_name = profile.display_name
        row.avatar_url = profile.avatar_url
        row.bio = profile.bio
        row.verified_at = profile.verified_at

    async def save_account(self, account: PlatformAccount) -> None:
        account_pk = parse_persistence_id(account.account_id, field="account_id")
        creator_pk = parse_persistence_id(account.creator_id, field="creator_id")
        row = await self.session.get(PlatformAccountModel, account_pk)
        if row is None:
            self.session.add(
                PlatformAccountModel(
                    id=account_pk,
                    creator_id=creator_pk,
                    legacy_anchor_id=None,
                    platform=account.platform,
                    platform_user_id=account.platform_user_id,
                    room_id=account.room_id,
                    canonical_url=account.canonical_url,
                    is_disabled=not account.enabled,
                )
            )
            return
        row.creator_id = creator_pk
        row.platform = account.platform
        row.platform_user_id = account.platform_user_id
        row.room_id = account.room_id
        row.canonical_url = account.canonical_url
        row.is_disabled = not account.enabled

    @staticmethod
    def _to_account(row: PlatformAccountModel) -> PlatformAccount:
        return PlatformAccount(
            account_id=serialize_persistence_id(row.id, field="account_id"),
            creator_id=serialize_persistence_id(row.creator_id, field="creator_id"),
            platform=row.platform,
            platform_user_id=row.platform_user_id,
            room_id=row.room_id,
            canonical_url=row.canonical_url,
            enabled=not row.is_disabled,
        )
