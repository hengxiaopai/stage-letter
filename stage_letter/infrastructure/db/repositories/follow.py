"""SQLAlchemy implementation of the formal FollowRepository port."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.infrastructure.db.models import FollowModel, NotificationPreferenceModel

from .identity import parse_persistence_id, serialize_persistence_id


class SQLAlchemyFollowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_follow(self, user_id: str, account_id: str) -> Follow | None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(FollowModel).where(
                FollowModel.user_id == user_pk,
                FollowModel.platform_account_id == account_pk,
            )
        )
        if row is None:
            return None
        return Follow(
            user_id=serialize_persistence_id(row.user_id, field="user_id"),
            creator_id=serialize_persistence_id(row.creator_id, field="creator_id"),
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            starred=row.starred,
        )

    async def save_follow(self, follow: Follow) -> None:
        user_pk = parse_persistence_id(follow.user_id, field="user_id")
        creator_pk = parse_persistence_id(follow.creator_id, field="creator_id")
        account_pk = parse_persistence_id(follow.account_id, field="account_id")
        row = await self.session.scalar(
            select(FollowModel).where(
                FollowModel.user_id == user_pk,
                FollowModel.platform_account_id == account_pk,
            )
        )
        if row is None:
            self.session.add(
                FollowModel(
                    user_id=user_pk,
                    creator_id=creator_pk,
                    platform_account_id=account_pk,
                    starred=follow.starred,
                )
            )
            return
        row.creator_id = creator_pk
        row.starred = follow.starred

    async def delete_follow(self, user_id: str, account_id: str) -> None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(FollowModel).where(
                FollowModel.user_id == user_pk,
                FollowModel.platform_account_id == account_pk,
            )
        )
        if row is not None:
            await self.session.delete(row)

    async def get_notification_preference(
        self,
        user_id: str,
        account_id: str,
    ) -> NotificationPreference | None:
        user_pk = parse_persistence_id(user_id, field="user_id")
        account_pk = parse_persistence_id(account_id, field="account_id")
        row = await self.session.scalar(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user_pk,
                NotificationPreferenceModel.platform_account_id == account_pk,
            )
        )
        if row is None:
            return None
        return NotificationPreference(
            user_id=serialize_persistence_id(row.user_id, field="user_id"),
            account_id=serialize_persistence_id(row.platform_account_id, field="account_id"),
            enabled=row.enabled,
            silent_start=row.silent_start,
            silent_end=row.silent_end,
        )

    async def save_notification_preference(
        self,
        preference: NotificationPreference,
    ) -> None:
        user_pk = parse_persistence_id(preference.user_id, field="user_id")
        account_pk = parse_persistence_id(preference.account_id, field="account_id")
        row = await self.session.scalar(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user_pk,
                NotificationPreferenceModel.platform_account_id == account_pk,
            )
        )
        if row is None:
            self.session.add(
                NotificationPreferenceModel(
                    user_id=user_pk,
                    platform_account_id=account_pk,
                    enabled=preference.enabled,
                    silent_start=preference.silent_start,
                    silent_end=preference.silent_end,
                )
            )
            return
        row.enabled = preference.enabled
        row.silent_start = preference.silent_start
        row.silent_end = preference.silent_end
