"""Creator/account application orchestration."""
from __future__ import annotations

from collections.abc import Callable

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount

UnitOfWorkFactory = Callable[[], UnitOfWork]


class CreatorApplicationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def save_bundle(
        self,
        creator: Creator,
        *,
        profile: CreatorProfile | None = None,
        account: PlatformAccount | None = None,
    ) -> None:
        if profile is not None and profile.creator_id != creator.creator_id:
            raise ApplicationInvariantError("profile creator_id mismatch")
        if account is not None and account.creator_id != creator.creator_id:
            raise ApplicationInvariantError("account creator_id mismatch")
        async with self._uow_factory() as uow:
            await uow.creators.save_creator(creator)
            if profile is not None:
                await uow.creators.save_profile(profile)
            if account is not None:
                await uow.creators.save_account(account)
            await uow.commit()
