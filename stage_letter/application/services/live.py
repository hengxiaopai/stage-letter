"""Durable live-observation ingestion orchestration."""
from __future__ import annotations

from collections.abc import Callable

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.live import LiveObservation

UnitOfWorkFactory = Callable[[], UnitOfWork]


class LiveObservationApplicationService:
    """Persist normalized observation facts without interpreting live-state truth."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def record(self, observation: LiveObservation) -> None:
        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(observation.account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {observation.account_id!r} not found"
                )
            await uow.live.append_observation(observation)
            await uow.commit()
