"""直播路由: 我订阅的正在直播 / 最近开播。

契约见 API-SPEC.md §6。
- GET /api/v1/lives/active: 我订阅的正在直播的主播
- GET /api/v1/lives/recent: 最近 24h 开播(全部)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

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

# Per-process admission control for the manual refresh endpoint. Provider work
# is additionally protected by the durable account lease below, so a process
# restart cannot create concurrent probes; this guard avoids needless repeated
# requests from the same Mini Program session during normal operation.
_REFRESH_COOLDOWNS: dict[str, datetime] = {}
_REFRESH_COOLDOWN_SECONDS = 30


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


class RefreshAcceptedResponse(BaseModel):
    """Accepted asynchronous refresh work; never misrepresent a stale snapshot."""

    status: Literal["accepted", "cooldown"] = "accepted"
    target_count: int
    poll_after_ms: int = 10_000
    cooldown_until: datetime


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
                started_at=ls.source_started_at or ls.started_at,
                viewer_count=ls.viewer_count,
                cover=ls.cover,
                started_at_source=ls.started_at_source or "probe",
            ),
            live_state=lstate["state"],
            freshness=lstate["freshness"],
            last_probe_at=lstate["last_probe_at"],
        ))
    return ActiveResponse(items=items)


@router.post("/lives/refresh", response_model=RefreshAcceptedResponse)
async def lives_refresh(
    openid: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RefreshAcceptedResponse:
    """P0-L3: 首页高优先级 Refresh — 对用户可见主播触发即时探测。

    前端 onShow 时调用: 拿到当前订阅主播, 后台立即探测一轮,
    返回明确的“已受理”契约。不阻塞 HTTP 请求；前端应在 poll_after_ms 后
    重新读取状态，而不是把此请求的旧快照误作最新探测结论。
    """
    user = await _get_or_create_user(db, openid)
    now = datetime.now(timezone.utc)
    existing_cooldown = _REFRESH_COOLDOWNS.get(openid)
    if existing_cooldown is not None and existing_cooldown > now:
        return RefreshAcceptedResponse(
            status="cooldown",
            target_count=0,
            poll_after_ms=max(
                1_000, int((existing_cooldown - now).total_seconds() * 1000)
            ),
            cooldown_until=existing_cooldown,
        )

    # 当前订阅的 platform_accounts(含 canonical_url)
    subs = (
        await db.execute(
            select(PlatformAccount)
            .join(UserSubscription, UserSubscription.platform_account_id == PlatformAccount.id)
            .where(UserSubscription.user_id == user.id)
        )
    ).scalars().all()

    # 触发当前用户订阅的优先探测（异步，不把 provider I/O 放进本请求的 DB 事务）。
    # 不能调用 run_once：它只会挑全库前一批 due 账号，既不保证覆盖当前用户，
    # 也不会在 Uvicorn 进程中自动加载 platform adapters。
    account_ids = list(dict.fromkeys(pa.id for pa in subs))
    cooldown_until = now + timedelta(seconds=_REFRESH_COOLDOWN_SECONDS)
    _REFRESH_COOLDOWNS[openid] = cooldown_until
    if account_ids:
        import asyncio

        async def _probe_account(account_id: int) -> bool:
            """Run one isolated probe and report whether a second confirmation is due."""
            try:
                from workers.probe.worker import _load_adapters, probe_one
                from core.live_session_engine import LiveSessionEngine
                from core.db import async_session
                from stage_letter.application.services.detection_lease import (
                    DetectionLeaseApplicationService,
                )
                from stage_letter.infrastructure.detection.leases import (
                    SQLAlchemyDetectionLeaseRepository,
                )

                _load_adapters()
                leases = DetectionLeaseApplicationService(
                    SQLAlchemyDetectionLeaseRepository(async_session)
                )
                async with async_session() as s:
                    engine = LiveSessionEngine(s)
                    owner_token = f"refresh:{uuid4().hex}"[:64]
                    lease_acquired = False
                    try:
                        # Same durable lease as the detection runtime: a manual
                        # refresh must not duplicate an in-flight worker probe.
                        acquisition = await leases.try_acquire(
                            account_id=str(account_id),
                            probe_id=f"monitor:manual-refresh:{uuid4().hex}",
                            owner_token=owner_token,
                        )
                        if not acquisition.acquired:
                            return False
                        lease_acquired = True
                        account = await s.get(PlatformAccount, account_id)
                        if account is None or account.is_disabled:
                            return False
                        await probe_one(s, account, engine)
                        await s.commit()
                        return account.last_status in ("SUSPECT_ONLINE", "SUSPECT_OFFLINE")
                    except Exception as account_error:
                        # A single platform's provider or persistence failure
                        # must not leave the shared session failed and prevent
                        # every later subscription from being refreshed.
                        await s.rollback()
                        import logging
                        logging.getLogger("stageletter.lives").warning(
                            "refresh probe account=%s: %s",
                            account_id,
                            account_error,
                        )
                        return False
                    finally:
                        if lease_acquired:
                            try:
                                await leases.release(
                                    account_id=str(account_id),
                                    owner_token=owner_token,
                                )
                            except Exception as lease_error:
                                import logging
                                logging.getLogger("stageletter.lives").warning(
                                    "refresh release lease account=%s: %s",
                                    account_id,
                                    lease_error,
                                )
            except Exception as e:
                import logging
                logging.getLogger("stageletter.lives").warning(
                    "refresh probe account=%s: %s", account_id, e
                )
                return False

        async def _confirm_after_delay(account_id: int) -> None:
            # The state machine intentionally needs two independent matching
            # observations. Do not wait for the next 60s worker sweep when the
            # user explicitly requested a refresh.
            await asyncio.sleep(8)
            await _probe_account(account_id)

        async def _probe_now(ids: list[int]):
            for account_id in ids:
                if await _probe_account(account_id):
                    asyncio.create_task(_confirm_after_delay(account_id))

        asyncio.create_task(_probe_now(account_ids))

    return RefreshAcceptedResponse(
        target_count=len(account_ids),
        cooldown_until=cooldown_until,
    )


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
            started_at=ls.source_started_at or ls.started_at,
            ended_at=ls.ended_at,
            started_at_source=ls.started_at_source or "probe",
        )
        for ls, a in rows
    ])
