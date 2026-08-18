"""订阅路由:用户订阅/取消订阅主播。

POST /api/v1/subscriptions           {user_id | openid, platform, platform_user_id} → 订阅
DELETE /api/v1/subscriptions/{id}    取消订阅
GET  /api/v1/subscriptions?openid=   列出我的订阅(openid 或 user_id 均可)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.live_state import from_platform_account
from core.models import Anchor, PlatformAccount, User, UserSubscription

router = APIRouter()


class SubscribeRequest(BaseModel):
    user_id: int | None = None
    openid: str | None = None
    platform: str  # douyin / bilibili / huya / douyu
    platform_user_id: str  # 平台侧 user_id 或 room_id
    canonical_url: str
    display_name: str | None = None
    avatar: str | None = None  # 主播头像(搜索/解析时拿到,存到 anchor)


class SubscriptionResponse(BaseModel):
    id: int
    anchor_id: int
    platform_account_id: int
    display_name: str | None = None
    avatar: str | None = None
    platform: str
    canonical_url: str
    # P0-L3 状态真相链统一字段
    is_live: bool | None = None   # True/False/None(未确认)
    live_state: str = "UNKNOWN"   # LIVE / OFFLINE / CONFIRMING / UNKNOWN
    freshness: str = "stale"      # fresh / stale / never
    last_probe_at: str | None = None


async def _resolve_user_id(db: AsyncSession, req: SubscribeRequest) -> int:
    """根据 user_id 或 openid 解析用户 id(openid 自动查/建)。"""
    if req.user_id is not None:
        return req.user_id
    if not req.openid:
        raise HTTPException(status_code=400, detail="user_id 或 openid 至少提供一个")
    r = await db.execute(select(User).where(User.openid == req.openid))
    user = r.scalar_one_or_none()
    if user is None:
        user = User(openid=req.openid)
        db.add(user)
        await db.flush()
    return user.id


@router.post("/subscriptions", response_model=SubscriptionResponse)
async def subscribe(
    req: SubscribeRequest, db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse:
    """订阅一个主播(upsert 语义:重复订阅返回已有记录)。"""
    user_id = await _resolve_user_id(db, req)

    # 1. upsert platform_account(唯一键 platform+platform_user_id)
    result = await db.execute(
        select(PlatformAccount).where(
            PlatformAccount.platform == req.platform,
            PlatformAccount.platform_user_id == req.platform_user_id,
        )
    )
    pa = result.scalar_one_or_none()

    if pa is None:
        # 创建 anchor + platform_account
        anchor = Anchor(display_name=req.display_name or req.platform_user_id)
        if req.avatar:
            anchor.avatar = req.avatar
        db.add(anchor)
        await db.flush()  # 拿 anchor.id

        pa = PlatformAccount(
            anchor_id=anchor.id,
            platform=req.platform,
            platform_user_id=req.platform_user_id,
            room_id=req.platform_user_id,
            canonical_url=req.canonical_url,
            last_status="OFFLINE",
            polling_tier="warm",
        )
        db.add(pa)
        await db.flush()
    else:
        anchor = await db.get(Anchor, pa.anchor_id)
        # 已有 anchor: 补头像;名字不同则更新为最新(搜索解析可能拿到更准的名字)
        if req.avatar and not anchor.avatar:
            anchor.avatar = req.avatar
        if req.display_name and anchor.display_name != req.display_name:
            anchor.display_name = req.display_name

    # 2. upsert subscription(唯一键 user_id+platform_account_id)
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id == user_id,
            UserSubscription.platform_account_id == pa.id,
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = UserSubscription(
            user_id=user_id,
            anchor_id=pa.anchor_id,
            platform_account_id=pa.id,
            notify_enabled=True,
        )
        db.add(sub)

    await db.commit()
    await db.refresh(sub)
    return SubscriptionResponse(
        id=sub.id,
        anchor_id=pa.anchor_id,
        platform_account_id=pa.id,
        display_name=anchor.display_name if anchor else None,
        avatar=anchor.avatar if anchor else None,
        platform=pa.platform,
        canonical_url=pa.canonical_url,
    )


async def _resolve_user_id_query(db: AsyncSession, openid: str | None, user_id: int | None) -> int:
    if user_id is not None:
        return user_id
    if not openid:
        raise HTTPException(status_code=400, detail="需要 openid 或 user_id")
    r = await db.execute(select(User).where(User.openid == openid))
    user = r.scalar_one_or_none()
    if user is None:
        user = User(openid=openid)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user.id


@router.get("/subscriptions")
async def list_subscriptions(
    openid: str | None = None,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionResponse]:
    """列出用户的订阅(openid 或 user_id)。"""
    uid = await _resolve_user_id_query(db, openid, user_id)
    result = await db.execute(
        select(UserSubscription, PlatformAccount, Anchor)
        .join(PlatformAccount, UserSubscription.platform_account_id == PlatformAccount.id)
        .join(Anchor, PlatformAccount.anchor_id == Anchor.id)
        .where(UserSubscription.user_id == uid)
    )
    out = []
    for sub, pa, anchor in result.all():
        # P0-L3: 统一 Current Live State(不再直接 last_status == ONLINE)
        ls = from_platform_account(pa)
        out.append(
            SubscriptionResponse(
                id=sub.id,
                anchor_id=anchor.id,
                platform_account_id=pa.id,
                display_name=anchor.display_name,
                avatar=anchor.avatar,
                platform=pa.platform,
                canonical_url=pa.canonical_url,
                is_live=ls["is_live"],
                live_state=ls["state"],
                freshness=ls["freshness"],
                last_probe_at=ls["last_probe_at"],
            )
        )
    return out


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def unsubscribe(sub_id: int, db: AsyncSession = Depends(get_db)) -> None:
    sub = await db.get(UserSubscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    await db.delete(sub)
    await db.commit()
