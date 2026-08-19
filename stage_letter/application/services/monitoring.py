"""Monitoring-target discovery for Gate 1.4.

This application service exposes only explicitly enabled PlatformAccount rows for
polling. It performs no provider I/O and does not interpret live-state truth.
"""
from __future__ import annotations

from collections.abc import Callable

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.creators import PlatformAccount

UnitOfWorkFactory = Callable[[], UnitOfWork]


class MonitoringTargetApplicationService:
    """Read stable, explicitly enabled monitoring targets in deterministic pages."""

    MAX_PAGE_SIZE = 1000
    DEFAULT_PAGE_SIZE = 100

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list_targets(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[PlatformAccount, ...]:
        if limit < 1 or limit > self.MAX_PAGE_SIZE:
            raise ApplicationInvariantError(
                f"monitoring target limit must be between 1 and {self.MAX_PAGE_SIZE}"
            )
        async with self._uow_factory() as uow:
            return await uow.creators.list_enabled_accounts(
                after_account_id=after_account_id,
                limit=limit,
            )
