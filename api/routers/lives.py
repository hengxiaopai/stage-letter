"""直播路由: 我订阅的正在直播 / 最近开播。

契约见 API-SPEC.md §6。
- GET /api/v1/lives/active: 我订阅的正在直播的主播
- GET /api/v1/lives/recent: 最近 24h 开播(全部)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.live_state import from_platform_account
from core.models import (
    Anchor,
    LiveSession,
    PlatformAccount,
    User,
    UserSubscription,
)

router = APIRouter()


class ActiveSession(BaseModel):
    id: int
    title: str | None = None
    started_at: datetime | None = None
    viewer_count: int | None = None
    cover: str | None = None
    # 2026-08-14: 开播时间来源 platform=真实 / probe=探测时刻兜底
    started_at_source: str = "probe"


class ActiveItem(BaseModel):
    anchor_id: int
    anchor_name: str
    anchor_avatar: str | None = None
    platform: str
    session: ActiveSession
    # P0-L3: 状态真相链字段(首页实时态)
    live_state: str = "LIVE"
    freshness: str = "fresh"
    last_probe_at: str | None = None


class ActiveResponse(BaseModel):
    items: list[ActiveItem]


class RecentItem(BaseModel):
    id: int
    anchor_id: int
    anchor_name: str | None = None
    platform: str
    title: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    # 2026-08-14: 开播时间来源 platform=真实 / probe=探测时刻兜底
    started_at_source: str = "probe"


class RecentResponse(BaseModel):
    items: list[RecentItem]


async def _get_or_create_user(db: AsyncSession, openid: str) -> User:
    r = await db.execute(select(User).where(User.openid == openid))
    user = r.scalar_one_or_none()
    if user is None:
        user = User(openid=openid)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


@router.get("/lives/active", response_model=ActiveResponse)
async def lives_active(
    openid: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> ActiveResponse:
    """我订阅的正在直播的主播(仅 LIVE 状态 — Live State → UI 唯一映射)。

    P0-L4: CONFIRMING(探测过期/进行中)不进 active, 由订阅接口携带
    live_state 供前端归入「状态确认中」区块; OFFLINE 归入等待开播。
    """
    user = await _get_or_create_user(db, openid)

    rows = (
        await db.execute(
            select(Anchor, PlatformAccount, LiveSession)
            .join(UserSubscription, UserSubscription.anchor_id == Anchor.id)
            .join(PlatformAccount, UserSubscription.platform_account_id == PlatformAccount.id)
            .join(LiveSession, LiveSession.platform_account_id == PlatformAccount.id)
            .where(
                UserSubscription.user_id == user.id,
                LiveSession.state == "OPEN",
            )
            .order_by(LiveSession.started_at.desc())
        )
    ).all()

    items = []
    for a, pa, ls in rows:
        # P0-L3: 统一 Current Live State; 只有确认 LIVE 才进「正在直播」
        lstate = from_platform_account(pa)
        if lstate["state"] != "LIVE":
            # CONFIRMING/UNKNOWN → 不算正在直播(由前端从订阅列表归入「确认中」)
            continue
        items.append(ActiveItem(
            anchor_id=a.id,
            anchor_name=a.display_name,
            anchor_avatar=a.avatar,
            platform=pa.platform,
            session=ActiveSession(
                id=ls.id,
                title=ls.title,
                started_at=ls.started_at,
                viewer_count=ls.viewer_count,
                cover=ls.cover,
                started_at_source=ls.started_at_source or "probe",
            ),
            live_state=lstate["state"],
            freshness=lstate["freshness"],
            last_probe_at=lstate["last_probe_at"],
        ))
    return ActiveResponse(items=items)


@router.post("/lives/refresh", response_model=ActiveResponse)
async def lives_refresh(
    openid: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> ActiveResponse:
    """P0-L3: 首页高优先级 Refresh — 对用户可见主播触发即时探测。

    前端 onShow 时调用: 拿到当前订阅主播, 后台立即探测一轮,
    返回探测后的最新 active 列表。不阻塞(后端异步探测, 此请求返回触发后快照)。
    """
    user = await _get_or_create_user(db, openid)

    # 当前订阅的 platform_accounts(含 canonical_url)
    subs = (
        await db.execute(
            select(PlatformAccount)
            .join(UserSubscription, UserSubscription.platform_account_id == PlatformAccount.id)
            .where(UserSubscription.user_id == user.id)
        )
    ).scalars().all()

    # 触发一轮即时探测(异步, 不等待完成 — 探测结果下次拉取生效)
    if subs:
        import asyncio

        async def _probe_now():
            try:
                from workers.probe.worker import run_once
                from core.live_session_engine import LiveSessionEngine
                from core.db import async_session

                async with async_session() as s:
                    await run_once(s, LiveSessionEngine(s))
            except Exception as e:
                import logging
                logging.getLogger("stageletter.lives").warning("refresh probe: %s", e)

        asyncio.create_task(_probe_now())

    # 返回当前快照(探测结果下一轮生效)
    return await lives_active(openid=openid, db=db)


@router.get("/lives/recent", response_model=RecentResponse)
async def lives_recent(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> RecentResponse:
    """最近 24h 开播(所有 session,含已结束)。"""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = (
        await db.execute(
            select(LiveSession, Anchor)
            .join(Anchor, LiveSession.anchor_id == Anchor.id)
            .where(LiveSession.started_at >= since)
            .order_by(LiveSession.started_at.desc())
            .limit(limit)
        )
    ).all()

    return RecentResponse(items=[
        RecentItem(
            id=ls.id,
            anchor_id=ls.anchor_id,
            anchor_name=a.display_name,
            platform=ls.platform,
            title=ls.title,
            started_at=ls.started_at,
            ended_at=ls.ended_at,
            started_at_source=ls.started_at_source or "probe",
        )
        for ls, a in rows
    ])
