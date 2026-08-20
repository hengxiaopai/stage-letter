"""Bounded, read-only operator inquiry for Gate 5.3."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Anchor, NotificationDelivery, PlatformAccount, User, UserSubscription


MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True)
class AdminPage:
    items: list[dict]
    next_cursor: str | None


def _limit(value: int) -> int:
    if value < 1 or value > MAX_PAGE_SIZE:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid limit")
    return value


def _cursor(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdigit() or int(value) < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid cursor")
    return int(value)


def _page(rows: list[dict], *, limit: int) -> AdminPage:
    kept = rows[:limit]
    next_cursor = str(kept[-1]["id"]) if len(rows) > limit and kept else None
    return AdminPage(items=kept, next_cursor=next_cursor)


async def list_users(db: AsyncSession, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None) -> AdminPage:
    limit, after = _limit(limit), _cursor(cursor)
    query = (
        select(
            User.id.label("id"),
            User.created_at.label("created_at"),
            User.last_active_at.label("last_active_at"),
            func.count(UserSubscription.id).label("subscription_count"),
        )
        .outerjoin(UserSubscription, UserSubscription.user_id == User.id)
        .group_by(User.id, User.created_at, User.last_active_at)
        .order_by(User.id)
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(User.id > after)
    rows = (await db.execute(query)).mappings().all()
    return _page([dict(row) for row in rows], limit=limit)


async def list_subscriptions(
    db: AsyncSession, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
) -> AdminPage:
    limit, after = _limit(limit), _cursor(cursor)
    query = (
        select(
            UserSubscription.id.label("id"),
            UserSubscription.user_id.label("user_id"),
            PlatformAccount.creator_id.label("creator_id"),
            Anchor.display_name.label("display_name"),
            PlatformAccount.platform.label("platform"),
            UserSubscription.notify_enabled.label("notify_enabled"),
            UserSubscription.created_at.label("created_at"),
        )
        .join(PlatformAccount, PlatformAccount.id == UserSubscription.platform_account_id)
        .join(Anchor, Anchor.id == UserSubscription.anchor_id)
        .order_by(UserSubscription.id)
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(UserSubscription.id > after)
    rows = (await db.execute(query)).mappings().all()
    return _page([dict(row) for row in rows], limit=limit)


async def list_deliveries(
    db: AsyncSession, *, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None
) -> AdminPage:
    limit, after = _limit(limit), _cursor(cursor)
    query = (
        select(
            NotificationDelivery.id.label("id"),
            NotificationDelivery.user_id.label("user_id"),
            NotificationDelivery.channel.label("channel"),
            NotificationDelivery.state.label("state"),
            NotificationDelivery.attempt.label("attempt"),
            NotificationDelivery.error_code.label("error_code"),
            NotificationDelivery.sent_at.label("sent_at"),
            NotificationDelivery.created_at.label("created_at"),
        )
        .order_by(NotificationDelivery.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        query = query.where(NotificationDelivery.id < after)
    rows = (await db.execute(query)).mappings().all()
    kept = [dict(row) for row in rows[:limit]]
    next_cursor = str(kept[-1]["id"]) if len(rows) > limit and kept else None
    return AdminPage(items=kept, next_cursor=next_cursor)


def page_payload(page: AdminPage) -> dict:
    """Serialize only the pre-sanitized read model; never expose ORM entities."""

    return {"items": page.items, "next_cursor": page.next_cursor}
