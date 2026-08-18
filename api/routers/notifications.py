"""通知相关路由: grant 查询 / request-grant / 历史记录。

契约见 API-SPEC.md §7(grant 模型,ADR-001/002):
- available = granted - consumed(应用层计算)
- request-grant: 客户端收到 wx.requestSubscribeMessage accept 后调用
- 限频: 同 user 5min 内重复 → 42902;同 user 1h 内 > 5 次 → 42903
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import get_db
from core.models import (
    Anchor,
    LiveSession,
    NotificationDelivery,
    NotificationJob,
    User,
    WechatSubscriptionGrant,
)

router = APIRouter()

DEFAULT_TEMPLATE = "wx_template_live_start"
GRANT_MIN_INTERVAL_S = 300   # 5min
GRANT_MAX_PER_HOUR = 5


class GrantResponse(BaseModel):
    template_id: str
    granted_count: int
    consumed_count: int
    available: int
    last_granted_at: datetime | None = None
    last_send_at: datetime | None = None
    last_send_error: str | None = None


class RequestGrantRequest(BaseModel):
    template_id: str = DEFAULT_TEMPLATE
    accept_count: int = 1


class RequestGrantResponse(BaseModel):
    template_id: str
    granted_count: int
    consumed_count: int
    available: int
    refreshed_at: datetime


async def _get_or_create_user(db: AsyncSession, openid: str) -> User:
    r = await db.execute(select(User).where(User.openid == openid))
    user = r.scalar_one_or_none()
    if user is None:
        user = User(openid=openid)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _get_grant(db: AsyncSession, user_id: int, template_id: str) -> WechatSubscriptionGrant | None:
    r = await db.execute(
        select(WechatSubscriptionGrant).where(
            WechatSubscriptionGrant.user_id == user_id,
            WechatSubscriptionGrant.template_id == template_id,
        )
    )
    return r.scalar_one_or_none()


def _to_grant_response(template_id: str, g: WechatSubscriptionGrant | None) -> GrantResponse:
    if g is None:
        return GrantResponse(
            template_id=template_id,
            granted_count=0,
            consumed_count=0,
            available=0,
        )
    return GrantResponse(
        template_id=template_id,
        granted_count=g.granted_count,
        consumed_count=g.consumed_count,
        available=g.granted_count - g.consumed_count,
        last_granted_at=g.last_granted_at,
        last_send_at=g.last_send_at,
        last_send_error=g.last_send_error,
    )


@router.get("/notifications/grants", response_model=GrantResponse)
async def get_grants(
    openid: str = Query(..., description="微信 openid(dev 阶段直接传,生产换 token)"),
    template_id: str = Query(DEFAULT_TEMPLATE),
    db: AsyncSession = Depends(get_db),
) -> GrantResponse:
    user = await _get_or_create_user(db, openid)
    grant = await _get_grant(db, user.id, template_id)
    return _to_grant_response(template_id, grant)


@router.post("/notifications/request-grant", response_model=RequestGrantResponse)
async def request_grant(
    req: RequestGrantRequest,
    openid: str = Query(..., description="微信 openid"),
    db: AsyncSession = Depends(get_db),
) -> RequestGrantResponse:
    user = await _get_or_create_user(db, openid)
    now = datetime.now(timezone.utc)
    template_id = req.template_id

    # 限频检查
    r = await db.execute(
        select(WechatSubscriptionGrant).where(
            WechatSubscriptionGrant.user_id == user.id,
            WechatSubscriptionGrant.template_id == template_id,
        )
    )
    grant = r.scalar_one_or_none()

    if grant and grant.last_granted_at:
        # 5min 内重复
        if now - grant.last_granted_at < timedelta(seconds=GRANT_MIN_INTERVAL_S):
            raise HTTPException(status_code=429, detail="重复请求,请 5 分钟后再试")
        # 1h 内 > 5 次
        hour_ago = now - timedelta(hours=1)
        recent_count = await db.execute(
            select(func.count())
            .select_from(WechatSubscriptionGrant)
            .where(
                WechatSubscriptionGrant.user_id == user.id,
                WechatSubscriptionGrant.template_id == template_id,
                WechatSubscriptionGrant.last_granted_at >= hour_ago,
            )
        )
        if recent_count.scalar() >= GRANT_MAX_PER_HOUR:
            raise HTTPException(status_code=429, detail="请求过于频繁,请稍后再试")

    # ADR-002: granted_count 可累积储备
    if grant is None:
        grant = WechatSubscriptionGrant(
            user_id=user.id,
            template_id=template_id,
            granted_count=req.accept_count,
            consumed_count=0,
            last_granted_at=now,
        )
        db.add(grant)
    else:
        grant.granted_count += req.accept_count
        grant.last_granted_at = now

    await db.commit()
    await db.refresh(grant)

    return RequestGrantResponse(
        template_id=template_id,
        granted_count=grant.granted_count,
        consumed_count=grant.consumed_count,
        available=grant.granted_count - grant.consumed_count,
        refreshed_at=now,
    )


class HistoryItem(BaseModel):
    id: int
    anchor_id: int
    display_name: str | None = None
    platform: str | None = None
    live_session_id: int | None = None
    started_at: datetime | None = None
    channel: str | None = None
    state: str
    error_code: str | None = None
    sent_at: datetime | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    next_cursor: str | None = None


@router.get("/notifications/history", response_model=HistoryResponse)
async def notification_history(
    openid: str = Query(...),
    limit: int = Query(20, ge=1, le=50),
    cursor: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    user = await _get_or_create_user(db, openid)

    rows = (
        await db.execute(
            select(NotificationDelivery, NotificationJob, LiveSession, Anchor)
            .join(NotificationJob, NotificationDelivery.notification_job_id == NotificationJob.id)
            .outerjoin(LiveSession, NotificationDelivery.live_session_id == LiveSession.id)
            .join(Anchor, NotificationJob.anchor_id == Anchor.id)
            .where(NotificationDelivery.user_id == user.id)
            .order_by(NotificationDelivery.id.desc())
            .offset(cursor)
            .limit(limit)
        )
    ).all()

    items = [
        HistoryItem(
            id=d.id,
            anchor_id=a.id,
            display_name=a.display_name,
            platform=ls.platform if ls else None,
            live_session_id=d.live_session_id,
            started_at=ls.started_at if ls else None,
            channel=d.channel,
            state=d.state,
            error_code=d.error_code,
            sent_at=d.sent_at,
        )
        for d, nj, ls, a in rows
    ]

    next_cursor = str(cursor + limit) if len(items) == limit else None
    return HistoryResponse(items=items, next_cursor=next_cursor)
