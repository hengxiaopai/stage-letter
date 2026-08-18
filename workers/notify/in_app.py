"""In-App 兜底投递 worker(Gate 3)。

独立于 wechat worker: 扫描长期未 DONE 的 PENDING job(如微信侧已 fallback
但 job 未标记),投递站内消息(站内通知即 notification_deliveries in_app 记录,
V1 阶段站内消息 = 小程序内未读列表,由 API 查询 in_app deliveries 展示)。

当前 V1 简化: wechat.py 的 fallback_in_app 已直接写 in_app delivery。
本 worker 兜底处理"残留 PENDING job"(如进程崩溃导致未处理)。

用法:
    python -m workers.notify.in_app --loop --interval 60
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from core.models import NotificationDelivery, NotificationJob

logger = logging.getLogger("stageletter.notify.inapp")

# 超过 1h 未处理的 PENDING job 视为残留
STALE_MINUTES = 60


async def run_once(db: AsyncSession) -> int:
    """把超过 1h 的 PENDING job 兜底为 in_app。"""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
    jobs = (
        await db.execute(
            select(NotificationJob).where(
                NotificationJob.state == "PENDING",
                NotificationJob.created_at < cutoff,
            )
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    for job in jobs:
        # 幂等: 若已有 in_app delivery 则跳过
        dup = await db.execute(
            select(NotificationDelivery.id).where(
                NotificationDelivery.notification_job_id == job.id,
                NotificationDelivery.channel == "in_app",
            )
        )
        if dup.scalar_one_or_none() is not None:
            job.state = "DONE"
            continue

        delivery = NotificationDelivery(
            notification_job_id=job.id,
            user_id=job.user_id,
            live_session_id=job.live_session_id,
            channel="in_app",
            state="SENT",
            error_code="stale_timeout",
            attempt=1,
            sent_at=now,
        )
        db.add(delivery)
        job.state = "DONE"
        logger.info("job=%s 残留超时 → in_app 兜底", job.id)
    await db.commit()
    return len(jobs)


async def loop(interval_s: int) -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("In-App worker 启动")
    while True:
        async with factory() as db:
            n = await run_once(db)
            if n:
                logger.info("本轮兜底 %d 个残留 job", n)
        await asyncio.sleep(interval_s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.loop:
        asyncio.run(loop(args.interval))
    else:
        asyncio.run(run_once)


if __name__ == "__main__":
    main()
