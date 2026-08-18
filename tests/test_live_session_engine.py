"""LiveSessionEngine 测试: 状态转换 + 去重。

用 Docker PostgreSQL(开发库,5433)跑 —— 这样能同时验证:
- 完整状态机转换
- partial unique index(同一 pa 一个 OPEN session)的 DB 级兜底
- fan-out job 去重 UNIQUE(live_event_id, user_id)

每次测试前清空相关表,测试互不干扰。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, text
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

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"

T0 = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)

# 清表顺序: 先子表后父表
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


async def seed(db: AsyncSession) -> dict:
    user = User(openid="test_openid_1", nickname="tester")
    db.add(user)
    await db.flush()
    anchor = Anchor(display_name="test_anchor")
    db.add(anchor)
    await db.flush()
    pa = PlatformAccount(
        anchor_id=anchor.id,
        platform="bilibili",
        platform_user_id="room_1",
        canonical_url="https://live.bilibili.com/1",
        last_status="OFFLINE",
    )
    db.add(pa)
    await db.flush()
    sub = UserSubscription(
        user_id=user.id,
        anchor_id=anchor.id,
        platform_account_id=pa.id,
        notify_enabled=True,
    )
    db.add(sub)
    await db.flush()
    return {"user": user, "anchor": anchor, "pa": pa, "sub": sub}


async def test_full_cycle_open_and_close(db: AsyncSession) -> None:
    await clean(db)
    s = await seed(db)
    engine = LiveSessionEngine(db)

    # OFFLINE + ONLINE → SUSPECT_ONLINE
    r1 = await engine.on_probe(s["pa"].id, "ONLINE", {"title": "t1"}, now=T0)
    assert r1["event"] == "SUSPECT_ONLINE"
    assert r1["session_id"] is None
    assert r1["job_count"] == 0

    # SUSPECT_ONLINE + ONLINE → CONFIRMED_ONLINE(建 session + fan-out)
    r2 = await engine.on_probe(s["pa"].id, "ONLINE", {"title": "t1"}, now=T0)
    assert r2["event"] == "CONFIRMED_ONLINE"
    assert r2["session_id"] is not None
    assert r2["job_count"] == 1

    # ONLINE + ONLINE → 无事件
    r3 = await engine.on_probe(s["pa"].id, "ONLINE", {"title": "t1"}, now=T0)
    assert r3["event"] is None

    # ONLINE + OFFLINE → SUSPECT_OFFLINE
    r4 = await engine.on_probe(s["pa"].id, "OFFLINE", now=T0)
    assert r4["event"] == "SUSPECT_OFFLINE"

    # SUSPECT_OFFLINE + OFFLINE → CONFIRMED_OFFLINE(关 session)
    r5 = await engine.on_probe(s["pa"].id, "OFFLINE", now=T0)
    assert r5["event"] == "CONFIRMED_OFFLINE"
    assert r5["session_id"] == r2["session_id"]

    await db.flush()

    ev_count = (await db.execute(select(func.count()).select_from(LiveEvent))).scalar()
    assert ev_count == 4

    sess = await db.get(LiveSession, r2["session_id"])
    assert sess.state == "CLOSED"
    assert sess.ended_at is not None

    job_count = (await db.execute(select(func.count()).select_from(NotificationJob))).scalar()
    assert job_count == 1
    print("✓ 完整循环: 开播建 session + fan-out,下播关 session")


async def test_dedup_no_double_open_session(db: AsyncSession) -> None:
    await clean(db)
    s = await seed(db)
    engine = LiveSessionEngine(db)

    await engine.on_probe(s["pa"].id, "ONLINE", now=T0)
    await engine.on_probe(s["pa"].id, "ONLINE", now=T0)  # CONFIRMED_ONLINE → session
    # 已 ONLINE,不会再有 CONFIRMED_ONLINE;但为验证引擎幂等,直接调用 _open_session
    await engine._open_session(s["pa"], {"title": "dup"}, T0)

    open_count = (
        await db.execute(
            select(func.count())
            .select_from(LiveSession)
            .where(LiveSession.state == "OPEN")
        )
    ).scalar()
    assert open_count == 1
    print("✓ 去重: 不会创建第二个 OPEN session")


async def test_jitter_only_one_confirmed(db: AsyncSession) -> None:
    """抖动测试: online→offline→online 5s 内,只产生一次 CONFIRMED_ONLINE。"""
    await clean(db)
    s = await seed(db)
    engine = LiveSessionEngine(db)
    t0 = T0

    # ONLINE → SUSPECT_ONLINE
    await engine.on_probe(s["pa"].id, "ONLINE", now=t0)
    # ONLINE → CONFIRMED_ONLINE(唯一一次开播确认)
    r = await engine.on_probe(s["pa"].id, "ONLINE", now=t0 + timedelta(seconds=1))
    assert r["event"] == "CONFIRMED_ONLINE"

    # 抖动: OFFLINE → SUSPECT_OFFLINE,然后又 ONLINE → 回到 ONLINE(无新 CONFIRMED)
    await engine.on_probe(s["pa"].id, "OFFLINE", now=t0 + timedelta(seconds=3))
    r2 = await engine.on_probe(s["pa"].id, "ONLINE", now=t0 + timedelta(seconds=4))
    assert r2["event"] is None  # 抖动不产生新事件
    assert r2["state"] == "ONLINE"

    # 再 OFFLINE 确认下播
    await engine.on_probe(s["pa"].id, "OFFLINE", now=t0 + timedelta(seconds=5))
    r3 = await engine.on_probe(s["pa"].id, "OFFLINE", now=t0 + timedelta(seconds=6))
    assert r3["event"] == "CONFIRMED_OFFLINE"

    # 断言: CONFIRMED_ONLINE 只有 1 次
    confirmed = (
        await db.execute(
            select(func.count())
            .select_from(LiveEvent)
            .where(LiveEvent.event_type == "CONFIRMED_ONLINE")
        )
    ).scalar()
    assert confirmed == 1
    print("✓ 抖动: online→offline→online 只产生一次 CONFIRMED_ONLINE")


async def test_dedup_no_double_job(db: AsyncSession) -> None:
    await clean(db)
    s = await seed(db)
    engine = LiveSessionEngine(db)

    await engine.on_probe(s["pa"].id, "ONLINE", now=T0)
    await engine.on_probe(s["pa"].id, "ONLINE", now=T0)  # 1 job

    # 拿到 event id,直接再 fanout 一次(模拟重放),验证 UNIQUE 兜底
    ev = (
        await db.execute(
            select(LiveEvent)
            .where(LiveEvent.event_type == "CONFIRMED_ONLINE")
            .limit(1)
        )
    ).scalar_one()
    await engine._fanout_jobs(s["pa"], ev.id, ev.live_session_id, T0)

    job_count = (await db.execute(select(func.count()).select_from(NotificationJob))).scalar()
    assert job_count == 1
    print("✓ 去重: 同一 (event, user) 只产生 1 个 job")


async def test_ratelimited_no_transition(db: AsyncSession) -> None:
    await clean(db)
    s = await seed(db)
    engine = LiveSessionEngine(db)

    for bad in ("RATE_LIMITED", "BLOCKED", "NOT_FOUND", "PARSE_ERROR", "UNKNOWN"):
        r = await engine.on_probe(s["pa"].id, bad, now=T0)
        assert r["event"] is None
        assert r["status_changed"] is False

    pa = await db.get(PlatformAccount, s["pa"].id)
    assert pa.last_status == "OFFLINE"
    print("✓ 限流/错误状态不触发转换")


async def main() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession)
    async with factory() as db:
        await test_full_cycle_open_and_close(db)
        await test_dedup_no_double_open_session(db)
        await test_dedup_no_double_job(db)
        await test_ratelimited_no_transition(db)
        await test_jitter_only_one_confirmed(db)
        print("\n✓ LiveSessionEngine 5 组测试全部通过(PG)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
