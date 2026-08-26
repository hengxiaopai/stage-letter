"""Gate 1 集成测试: 注入 1000 个 LiveEvent,验证去重不重不漏。

场景设计(模拟 10 个主播的真实开播/下播):
- 10 个 platform_accounts,每个 2 个订阅用户 = 20 用户
- 每个主播交替 ONLINE/OFFLINE 探测 50 次(25 次开播 + 25 次下播)
- 每次开播: CONFIRMED_ONLINE 事件 1 条 + OPEN session 1 个 + fan-out 2 jobs
- 每次下播: CONFIRMED_OFFLINE 事件 1 条 + session CLOSED

期望(不重不漏):
- LiveEvent 总数 = 1000(正好)
- OPEN session 数 = 10(每个主播 1 个)
- NotificationJob 总数 = 10 主播 × 25 次开播 × 2 用户 = 500
- 无重复: OPEN session 每个 pa 最多 1 个;job 每个 (event,user) 唯一

关键: 状态机转换只产生确定数量的事件 —— OFFLINE→ONLINE 序列:
  probe#1 ONLINE → SUSPECT_ONLINE
  probe#2 ONLINE → CONFIRMED_ONLINE(1 事件 + 1 session + 2 jobs)
  probe#3 OFFLINE → SUSPECT_OFFLINE
  probe#4 OFFLINE → CONFIRMED_OFFLINE(1 事件)
  每 4 次探测 = 2 事件(1 开播 + 1 下播)
  50 次探测 = 12.5 轮 → 25 事件/主播 → 10 主播 = 250 事件

等一下: 50 次探测是 12 轮完整 + 2 次残留。为精确到 1000,直接构造
100 次探测/主播 = 25 完整轮 = 50 事件/主播 → 10 主播 = 500 事件。
但要求是"注入 1000 个 LiveEvent" —— 用 100 次探测得到 500 事件,再
把"不重不漏"断言建立在"每个 CONFIRMED_ONLINE 只有 1 条 event 记录"
的幂等性上: 手动重放同一探测序列,事件数不翻倍。

最终方案(验证三重幂等):
A. 100 次探测/主播 → 记录事件数 E1 = 500(不重不漏的基准)
B. 重放同一序列 → 事件数仍 = 500(无重复)
C. job 总数 = 主播 × 开播次数 × 订阅数 = 10 × 25 × 2 = 500
D. 1000 断言: E1(500) + B 重放验证(仍 500) + job(500) = 1500?
   不对,这样数字不优雅。改为: 20 主播 × 100 探测 = 50 事件/主播 = 1000 事件。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.live_session_engine import LiveSessionEngine
from core.models import (
    Anchor,
    LiveEvent,
    LiveSession,
    NotificationJob,
    PlatformAccount,
    User,
    UserSubscription,
)

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5643/stageletter"

# 规模: 10 主播 × 100 次探测 = 每主播 100 事件(25 轮 × 4 事件)= 1000 事件
ANCHOR_COUNT = 10
PROBES_PER_ANCHOR = 100  # 25 完整轮(ONLINE,ONLINE,OFFLINE,OFFLINE)×25 = 100 事件/主播
USERS_PER_ANCHOR = 2
EXPECTED_EVENTS = ANCHOR_COUNT * 100  # 1000
EXPECTED_OPEN_SESSIONS = 0  # 序列最后停在 OFFLINE,所有 session 已 CLOSED
EXPECTED_CLOSED_SESSIONS = ANCHOR_COUNT * 25  # 25 次开播 → 25 个 CLOSED session/主播
EXPECTED_JOBS = ANCHOR_COUNT * 25 * USERS_PER_ANCHOR  # 25 次开播 × 2 用户 = 500

T0 = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)

CLEAN_TABLES = [
    "notification_deliveries",
    "notification_jobs",
    "live_events",
    "live_sessions",
    "user_subscriptions",
    "platform_accounts",
    "wechat_subscription_grants",
    "anchors",
    "users",
    "platform_health",
    "probe_runs",
]


async def clean(db: AsyncSession) -> None:
    for t in CLEAN_TABLES:
        await db.execute(text(f"DELETE FROM {t}"))


async def seed_all(db: AsyncSession) -> list[dict]:
    """创建 ANCHOR_COUNT 个主播,每个 USERS_PER_ANCHOR 个订阅用户。"""
    records = []
    for ai in range(ANCHOR_COUNT):
        user_ids = []
        for ui in range(USERS_PER_ANCHOR):
            u = User(openid=f"user_{ai}_{ui}", nickname=f"u{ai}_{ui}")
            db.add(u)
            await db.flush()
            user_ids.append(u.id)

        anchor = Anchor(display_name=f"anchor_{ai}")
        db.add(anchor)
        await db.flush()

        pa = PlatformAccount(
            anchor_id=anchor.id,
            platform="bilibili",
            platform_user_id=f"room_{ai}",
            canonical_url=f"https://live.bilibili.com/{ai}",
            last_status="OFFLINE",
        )
        db.add(pa)
        await db.flush()

        for uid in user_ids:
            sub = UserSubscription(
                user_id=uid,
                anchor_id=anchor.id,
                platform_account_id=pa.id,
                notify_enabled=True,
            )
            db.add(sub)
            await db.flush()

        records.append({"pa": pa, "user_ids": user_ids})
    return records


def probe_sequence() -> list[str]:
    """100 次探测序列: (ONLINE, ONLINE, OFFLINE, OFFLINE) × 25。"""
    seq = []
    for _ in range(25):
        seq += ["ONLINE", "ONLINE", "OFFLINE", "OFFLINE"]
    return seq


async def run_sequence(db: AsyncSession, records: list[dict], engine: LiveSessionEngine) -> int:
    """对每个主播跑探测序列,返回累计 CONFIRMED_ONLINE 次数。"""
    online_count = 0
    for rec in records:
        seq = probe_sequence()
        for i, status in enumerate(seq):
            meta = {"title": f"anchor_{rec['pa'].anchor_id}_probe{i}", "viewer_count": i}
            r = await engine.on_probe(rec["pa"].id, status, meta, now=T0 + timedelta(minutes=i))
            if r["event"] == "CONFIRMED_ONLINE":
                online_count += 1
    await db.flush()
    return online_count


async def main() -> int:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession)
    async with factory() as db:
        await clean(db)
        records = await seed_all(db)

        # A. 第一遍跑序列
        le = LiveSessionEngine(db)
        online_1 = await run_sequence(db, records, le)
        print(f"A. 第一遍: CONFIRMED_ONLINE {online_1} 次")

        # 统计
        ev_count = (await db.execute(select(func.count()).select_from(LiveEvent))).scalar()
        open_sessions = (
            await db.execute(
                select(func.count()).select_from(LiveSession).where(LiveSession.state == "OPEN")
            )
        ).scalar()
        closed_sessions = (
            await db.execute(
                select(func.count()).select_from(LiveSession).where(LiveSession.state == "CLOSED")
            )
        ).scalar()
        job_count = (await db.execute(select(func.count()).select_from(NotificationJob))).scalar()
        print(f"    LiveEvent={ev_count}(期望 {EXPECTED_EVENTS})")
        print(f"    OPEN session={open_sessions}(期望 {EXPECTED_OPEN_SESSIONS})")
        print(f"    CLOSED session={closed_sessions}(期望 {EXPECTED_CLOSED_SESSIONS})")
        print(f"    NotificationJob={job_count}(期望 {EXPECTED_JOBS})")

        assert ev_count == EXPECTED_EVENTS, f"事件数不符: {ev_count} != {EXPECTED_EVENTS}"
        assert open_sessions == EXPECTED_OPEN_SESSIONS, f"OPEN 数不符: {open_sessions}"
        assert closed_sessions == EXPECTED_CLOSED_SESSIONS, f"CLOSED 数不符: {closed_sessions}"
        assert job_count == EXPECTED_JOBS, f"job 数不符: {job_count} != {EXPECTED_JOBS}"

        # B. 幂等性: 对同一 (event, user) 重放 fan-out,数量不变(UNIQUE 兜底)
        # 取 pa0 的 CONFIRMED_ONLINE 事件(它已 fan-out 过 2 个 job)
        pa0 = records[0]["pa"]
        ev = (
            await db.execute(
                select(LiveEvent)
                .where(
                    LiveEvent.platform_account_id == pa0.id,
                    LiveEvent.event_type == "CONFIRMED_ONLINE",
                )
                .limit(1)
            )
        ).scalar_one()
        await le._fanout_jobs(pa0, ev.id, ev.live_session_id, T0)
        job_count2 = (
            await db.execute(select(func.count()).select_from(NotificationJob))
        ).scalar()
        assert job_count2 == job_count, f"fan-out 幂等性破坏: {job_count2} != {job_count}"
        print(f"B. 重放 fan-out: job 数不变({job_count2}),UNIQUE 兜底生效")

        # C. 唯一性检查: 每个 OPEN session 对应唯一 pa
        dup_check = await db.execute(
            text(
                "SELECT platform_account_id, COUNT(*) FROM live_sessions "
                "WHERE state='OPEN' GROUP BY platform_account_id HAVING COUNT(*) > 1"
            )
        )
        dups = dup_check.all()
        assert len(dups) == 0, f"存在重复 OPEN session: {dups}"

        # D. 事件类型分布
        dist = await db.execute(
            select(LiveEvent.event_type, func.count()).group_by(LiveEvent.event_type)
        )
        print("C. 事件类型分布:")
        for et, cnt in dist.all():
            print(f"    {et}: {cnt}")
            if et in ("CONFIRMED_ONLINE", "CONFIRMED_OFFLINE"):
                assert cnt == ANCHOR_COUNT * 25, f"{et} 数量不符"
        print("\n✓✓ 集成测试通过: 1000 事件不重不漏,去重约束全部生效")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
