"""WeChat 投递 worker(Gate 3 Notification Engine)。

消费 notification_jobs(PENDING),按 grant 决策树发送微信订阅消息:

    job(PENDING)
      ├─ 用户无 grant → in_app fallback(reason='no_grant')
      ├─ send 返回 0       → delivery SENT, consumed+1
      ├─ 43101(拒收/无授权) → delivery FAILED, consumed+1(grant 失效)
      ├─ 40037(模板错误)    → delivery FAILED, disable 模板(platform_adapters 不受影响)
      ├─ 45009(限流)       → 退避重试(指数),grant 保留
      ├─ 5xx/网络           → 退避重试(指数),grant 保留
      └─ 其他 4xx           → 退避重试

grant 模型(ADR-001/002, Gate 0A 实测):
- available = granted - consumed
- granted_count 可累积储备(连续授权 N 次 = N 条)
- authority = send 返回码(伪造 accept 在余额 0 时必返 43101)

用法:
    python -m workers.notify.wechat --loop --interval 10
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.services.wechat import WeChatClient, WeChatError, get_wechat_client
from core.config import settings
from core.models import (
    LiveSession,
    NotificationDelivery,
    NotificationJob,
    PlatformAccount,
    User,
    WechatSubscriptionGrant,
)

logger = logging.getLogger("stageletter.notify.wechat")

# 微信错误码语义(Gate 0A 实测确认)
ERR_USER_REFUSE = 43101   # 用户拒收/未授权 → grant 失效,fallback in_app
ERR_TEMPLATE_INVALID = 40037  # 模板不存在/禁用 → disable 模板
ERR_RATE_LIMIT = 45009    # 接口限流 → 退避重试
ERR_TOKEN_INVALID = 40001  # token 无效 → 刷新重试
ERR_ACCESS_TOKEN_EXPIRED = 42001  # token 过期 → 刷新重试

# 退避参数(秒),指数增长 10s → 20s → 40s → ... → 上限 5min
BACKOFF_BASE_S = 10
BACKOFF_MAX_S = 300
MAX_ATTEMPTS = 8


def backoff_s(attempt: int) -> int:
    return min(BACKOFF_BASE_S * (2 ** attempt), BACKOFF_MAX_S)


async def get_grant(
    db: AsyncSession, user_id: int, template_id: str
) -> WechatSubscriptionGrant | None:
    r = await db.execute(
        select(WechatSubscriptionGrant).where(
            WechatSubscriptionGrant.user_id == user_id,
            WechatSubscriptionGrant.template_id == template_id,
        )
    )
    return r.scalar_one_or_none()


async def get_or_create_grant(
    db: AsyncSession, user_id: int, template_id: str
) -> WechatSubscriptionGrant:
    g = await get_grant(db, user_id, template_id)
    if g is None:
        g = WechatSubscriptionGrant(user_id=user_id, template_id=template_id)
        db.add(g)
        await db.flush()
    return g


def grant_available(g: WechatSubscriptionGrant) -> int:
    return g.granted_count - g.consumed_count


async def fallback_in_app(
    db: AsyncSession, job: NotificationJob, live_session_id: int | None,
    reason: str, now: datetime,
) -> None:
    """In-App 兜底投递(站内消息通道)。"""
    delivery = NotificationDelivery(
        notification_job_id=job.id,
        user_id=job.user_id,
        live_session_id=live_session_id,
        channel="in_app",
        state="SENT",
        error_code=reason,
        attempt=1,
        sent_at=now,
    )
    db.add(delivery)
    job.state = "DONE"
    logger.info("job=%s → in_app fallback(%s)", job.id, reason)


async def record_delivery(
    db: AsyncSession,
    job: NotificationJob,
    live_session_id: int | None,
    channel: str,
    state: str,
    error_code: str | None,
    attempt: int,
    now: datetime,
) -> None:
    delivery = NotificationDelivery(
        notification_job_id=job.id,
        user_id=job.user_id,
        live_session_id=live_session_id,
        channel=channel,
        state=state,
        error_code=error_code,
        attempt=attempt,
        sent_at=now if state == "SENT" else None,
    )
    db.add(delivery)


async def process_job(
    db: AsyncSession,
    job: NotificationJob,
    client: WeChatClient,
    template_id: str,
) -> str:
    """处理单个 job,返回最终状态。"""
    now = datetime.now(timezone.utc)
    live_session = await db.get(LiveSession, job.live_session_id)

    anchor_name = f"主播 {job.anchor_id}"
    room_title = live_session.title if live_session else "开播了"

    # ── grant 决策树 ──
    grant = await get_or_create_grant(db, job.user_id, template_id)
    if grant_available(grant) <= 0:
        await fallback_in_app(db, job, job.live_session_id, reason="no_grant", now=now)
        await db.flush()
        return "FALLBACK_NO_GRANT"

    # 有 grant → 构造 payload 并发送
    session_title = live_session.title if live_session else ""
    payload = client.build_live_start_payload(
        anchor_name=anchor_name,
        room_title=room_title,
        start_time=live_session.started_at.strftime("%Y-%m-%d %H:%M") if live_session else now.strftime("%Y-%m-%d %H:%M"),
        theme=session_title[:20] if session_title else "开播提醒",
    )

    # 通过 user 拿 openid
    user = await db.get(User, job.user_id)
    if user is None or not user.openid:
        await fallback_in_app(db, job, job.live_session_id, reason="no_openid", now=now)
        await db.flush()
        return "FALLBACK_NO_OPENID"

    resp = client.send_subscribe_message(
        openid=user.openid,
        template_id=template_id,
        data=payload,
    )
    errcode = resp.get("errcode", -1)

    if errcode == 0:
        # 成功: consumed +1
        grant.consumed_count += 1
        grant.last_send_at = now
        await record_delivery(db, job, job.live_session_id, "wechat", "SENT", None, job.attempt + 1, now)
        job.state = "DONE"
        await db.flush()
        return "SENT"

    if errcode == ERR_USER_REFUSE:
        # 用户拒收/未授权: grant 失效,consumed +1,fallback in_app
        grant.consumed_count += 1
        grant.last_send_at = now
        grant.last_send_error = f"{errcode}"
        await record_delivery(db, job, job.live_session_id, "wechat", "FAILED", f"{errcode}", job.attempt + 1, now)
        await fallback_in_app(db, job, job.live_session_id, reason=f"wx_{errcode}", now=now)
        await db.flush()
        return "FALLBACK_REFUSED"

    if errcode == ERR_TEMPLATE_INVALID:
        # 模板错误: disable 模板(platform_adapters 不受影响),grant 保留
        await record_delivery(db, job, job.live_session_id, "wechat", "FAILED", f"{errcode}", job.attempt + 1, now)
        await fallback_in_app(db, job, job.live_session_id, reason=f"wx_{errcode}", now=now)
        await db.flush()
        logger.error("模板 %s 无效(40037),需人工确认;已 fallback in_app", template_id)
        return "TEMPLATE_DISABLED"

    if errcode in (ERR_RATE_LIMIT, ERR_TOKEN_INVALID, ERR_ACCESS_TOKEN_EXPIRED) or errcode >= 500:
        # 限流/token/5xx: 退避重试,grant 保留
        job.attempt += 1
        if job.attempt >= MAX_ATTEMPTS:
            await fallback_in_app(db, job, job.live_session_id, reason=f"wx_{errcode}_retry_exhausted", now=now)
            await db.flush()
            return "FALLBACK_RETRY_EXHAUSTED"
        job.state = "PENDING"
        job.next_retry_at = now + timedelta(seconds=backoff_s(job.attempt))
        await record_delivery(db, job, job.live_session_id, "wechat", "FAILED", f"{errcode}", job.attempt, now)
        await db.flush()
        return f"RETRY_{errcode}"

    # 其他 4xx: 退避重试
    job.attempt += 1
    if job.attempt >= MAX_ATTEMPTS:
        await fallback_in_app(db, job, job.live_session_id, reason=f"wx_{errcode}_retry_exhausted", now=now)
        await db.flush()
        return "FALLBACK_RETRY_EXHAUSTED"
    job.state = "PENDING"
    job.next_retry_at = now + timedelta(seconds=backoff_s(job.attempt))
    await record_delivery(db, job, job.live_session_id, "wechat", "FAILED", f"{errcode}", job.attempt, now)
    await db.flush()
    return f"RETRY_{errcode}"


async def run_once(db: AsyncSession, client: WeChatClient, template_id: str) -> int:
    """取一批到期 PENDING job 处理(含退避到期)。"""
    now = datetime.now(timezone.utc)
    jobs = (
        await db.execute(
            select(NotificationJob)
            .where(
                NotificationJob.state == "PENDING",
                (NotificationJob.next_retry_at.is_(None))
                | (NotificationJob.next_retry_at <= now),
            )
            .order_by(NotificationJob.id)
            .limit(20)
        )
    ).scalars().all()

    if not jobs:
        return 0

    for job in jobs:
        try:
            status = await process_job(db, job, client, template_id)
            logger.info("job=%s → %s", job.id, status)
        except Exception as e:
            logger.error("job=%s 处理异常: %s", job.id, e)
            await db.rollback()
        finally:
            await db.commit()
    return len(jobs)


async def loop(interval_s: int) -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = get_wechat_client()
    template_id = settings.wx_template_live_start
    if not template_id:
        logger.error("WX_TEMPLATE_LIVE_START 未配置,退出")
        return
    logger.info("WeChat notify worker 启动(template=%s...)", template_id[:12])

    while True:
        async with factory() as db:
            n = await run_once(db, client, template_id)
            if n:
                logger.info("本轮处理 %d 个 job", n)
        await asyncio.sleep(interval_s)


async def once() -> int:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = get_wechat_client()
    template_id = settings.wx_template_live_start
    async with factory() as db:
        n = await run_once(db, client, template_id)
        logger.info("单轮处理 %d 个 job", n)
        return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true", help="持续循环")
    ap.add_argument("--interval", type=int, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.loop:
        asyncio.run(loop(args.interval))
    else:
        asyncio.run(once())


if __name__ == "__main__":
    main()
