"""Read-only notification history application service."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.notification_history import NotificationHistoryEntry

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class NotificationHistoryPage:
    items: tuple[NotificationHistoryEntry, ...]
    next_cursor: str | None


class NotificationHistoryApplicationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> NotificationHistoryPage:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        before_delivery_id: int | None = None
        if cursor is not None:
            if not cursor.isdigit() or int(cursor) < 1:
                raise ValueError("cursor is invalid")
            before_delivery_id = int(cursor)

        async with self._uow_factory() as uow:
            rows = await uow.notifications.list_history_for_user(
                user_id,
                before_delivery_id=before_delivery_id,
                limit=limit + 1,
            )

        items = rows[:limit]
        next_cursor = str(items[-1].delivery_id) if len(rows) > limit else None
        return NotificationHistoryPage(items=items, next_cursor=next_cursor)
