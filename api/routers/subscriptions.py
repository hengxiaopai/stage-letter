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
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    CreatorProfileModel,
    FollowModel,
    NotificationPreferenceModel,
)

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


async def _ensure_formal_creator(
    db: AsyncSession,
    *,
    creator_id: int,
    display_name: str | None,
    avatar: str | None,
) -> CreatorProfileModel:
    """Keep the Gate 1 canonical creator/profile beside the legacy Anchor bridge."""
    creator = await db.get(CreatorModel, creator_id)
    if creator is None:
        db.add(CreatorModel(id=creator_id))

    profile = await db.scalar(
        select(CreatorProfileModel).where(CreatorProfileModel.creator_id == creator_id)
    )
    if profile is None:
        profile = CreatorProfileModel(
            creator_id=creator_id,
            display_name=display_name,
            avatar_url=avatar,
        )
        db.add(profile)
    else:
        if display_name:
            profile.display_name = display_name
        if avatar and not profile.avatar_url:
            profile.avatar_url = avatar
    await db.flush()
    return profile


async def _ensure_formal_follow(
    db: AsyncSession,
    *,
    user_id: int,
    creator_id: int,
    platform_account_id: int,
) -> None:
    """Dual-write the temporary legacy subscription and Gate 1 formal truth."""
    follow = await db.scalar(
        select(FollowModel).where(
            FollowModel.user_id == user_id,
            FollowModel.platform_account_id == platform_account_id,
        )
    )
    if follow is None:
        db.add(
            FollowModel(
                user_id=user_id,
                creator_id=creator_id,
                platform_account_id=platform_account_id,
                starred=False,
            )
        )

    preference = await db.scalar(
        select(NotificationPreferenceModel).where(
            NotificationPreferenceModel.user_id == user_id,
            NotificationPreferenceModel.platform_account_id == platform_account_id,
        )
    )
    if preference is None:
        db.add(
            NotificationPreferenceModel(
                user_id=user_id,
                platform_account_id=platform_account_id,
                enabled=True,
            )
        )
    else:
        preference.enabled = True


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

        # Gate 1 migration froze a deterministic identity bridge: legacy
        # anchor.id == formal creator.id.  Create the canonical owner first so
        # platform_accounts.creator_id can never be NULL.
        await _ensure_formal_creator(
            db,
            creator_id=anchor.id,
            display_name=anchor.display_name,
            avatar=anchor.avatar,
        )

        pa = PlatformAccount(
            anchor_id=anchor.id,
            creator_id=anchor.id,
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
        await _ensure_formal_creator(
            db,
            creator_id=pa.creator_id,
            display_name=anchor.display_name,
            avatar=anchor.avatar,
        )

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

    await _ensure_formal_follow(
        db,
        user_id=user_id,
        creator_id=pa.creator_id,
        platform_account_id=pa.id,
    )

    await db.commit()
    await db.refresh(sub)
    return SubscriptionResponse(
        id=sub.id,
        anchor_id=pa.creator_id,
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
                anchor_id=pa.creator_id,
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
    follow = await db.scalar(
        select(FollowModel).where(
            FollowModel.user_id == sub.user_id,
            FollowModel.platform_account_id == sub.platform_account_id,
        )
    )
    preference = await db.scalar(
        select(NotificationPreferenceModel).where(
            NotificationPreferenceModel.user_id == sub.user_id,
            NotificationPreferenceModel.platform_account_id == sub.platform_account_id,
        )
    )
    if follow is not None:
        await db.delete(follow)
    if preference is not None:
        await db.delete(preference)
    await db.delete(sub)
    await db.commit()
