"""Follow and notification-preference application orchestration."""
from __future__ import annotations

from collections.abc import Callable

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.follows import Follow, NotificationPreference

UnitOfWorkFactory = Callable[[], UnitOfWork]


class FollowApplicationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def follow_account(
        self,
        *,
        user_id: str,
        account_id: str,
        starred: bool = False,
    ) -> Follow:
        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(account_id)
            if account is None:
                raise ApplicationNotFoundError(f"platform account {account_id!r} not found")
            follow = Follow(
                user_id=user_id,
                creator_id=account.creator_id,
                account_id=account_id,
                starred=starred,
            )
            await uow.follows.save_follow(follow)
            await uow.commit()
            return follow

    async def unfollow_account(self, *, user_id: str, account_id: str) -> None:
        async with self._uow_factory() as uow:
            await uow.follows.delete_follow(user_id, account_id)
            await uow.commit()

    async def set_notification_preference(
        self,
        preference: NotificationPreference,
    ) -> None:
        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(preference.account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {preference.account_id!r} not found"
                )
            await uow.follows.save_notification_preference(preference)
            await uow.commit()
