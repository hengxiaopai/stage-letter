"""live_session_engine 开播时间真值测试 — 2026-08-14 固化。

运行: python -m tests.test_session_started_at
覆盖:
  1. 新开播 → session.started_at 用平台真实开播时间(非探测时刻)
  2. 已在播(ONLINE+ONLINE 不触发事件) → 回填更早真实时间, 不重复建 session
  3. 无真实时间(抖音匿名) → fallback 探测时刻
  4. 更晚时间戳不回填(防覆盖真实值)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from core.db import async_session
from core.live_session_engine import LiveSessionEngine
from core.models import Anchor, LiveEvent, LiveSession, NotificationJob, PlatformAccount, UserSubscription


async def _run() -> None:
    async with async_session() as db:
        anchor = Anchor(display_name="测试回填主播")
        db.add(anchor)
        await db.flush()
        pa = PlatformAccount(
            anchor_id=anchor.id,
            platform="bilibili",
            platform_user_id="TEST_FILL_001",
            room_id="TEST_FILL_001",
            canonical_url="https://live.bilibili.com/999999",
            last_status="OFFLINE",
            polling_tier="warm",
        )
        db.add(pa)
        await db.flush()
        engine = LiveSessionEngine(db)
        now = datetime.now(timezone.utc)
        real_ts = int(now.timestamp()) - 3 * 3600

        # 场景 1: 两轮探测确认开播, 第二轮带真实时间
        await engine.on_probe(pa.id, "ONLINE", {"title": "t"}, now=now)
        r2 = await engine.on_probe(
            pa.id, "ONLINE", {"title": "t", "live_started_at": real_ts}, now=now
        )
        assert r2["session_id"], "第二次探测应建 session"
        sess = await db.get(LiveSession, r2["session_id"])
        exp = datetime.fromtimestamp(real_ts, tz=timezone.utc)
        assert abs((sess.started_at - exp).total_seconds()) < 5, "未用真实开播时间"
        print("  ✓ 场景1 新建 session 用真实开播时间")

        # 场景 2: 已在播再次探测(更早时间) → 不建新 session, 回填生效
        real_ts2 = real_ts - 3600
        dup = await engine.on_probe(
            pa.id, "ONLINE", {"title": "t", "live_started_at": real_ts2}, now=now
        )
        assert dup["session_id"] is None, "ONLINE+ONLINE 不应建新 session"
        sess2 = await db.get(LiveSession, r2["session_id"])
        exp2 = datetime.fromtimestamp(real_ts2, tz=timezone.utc)
        assert abs((sess2.started_at - exp2).total_seconds()) < 5, "未回填"
        print("  ✓ 场景2 已在播回填更早真实时间(不重复建 session)")

        # 场景 3: 下播→再开播, 无 live_started_at(抖音) → fallback 探测时刻
        await engine.on_probe(pa.id, "OFFLINE", {}, now=now)
        await engine.on_probe(pa.id, "OFFLINE", {}, now=now)
        await engine.on_probe(pa.id, "ONLINE", {}, now=now)
        r3b = await engine.on_probe(pa.id, "ONLINE", {"title": "无时间"}, now=now)
        sess3 = await db.get(LiveSession, r3b["session_id"])
        assert abs((sess3.started_at - now).total_seconds()) < 5, "fallback 应为探测时刻"
        print("  ✓ 场景3 无真实时间 fallback 探测时刻")

        # 场景 4: 更晚时间戳不回填(防覆盖)
        future_ts = int(now.timestamp()) + 3600
        await engine.on_probe(
            pa.id, "ONLINE", {"title": "t", "live_started_at": future_ts}, now=now
        )
        sess4 = await db.get(LiveSession, r2["session_id"])
        assert abs((sess4.started_at - exp2).total_seconds()) < 5, "更晚时间不应覆盖"
        print("  ✓ 场景4 更晚时间不回填(防覆盖)")

        # 清理(先删引用外键的 events/jobs, 再删 sessions)
        await db.execute(delete(LiveEvent).where(LiveEvent.anchor_id == anchor.id))
        await db.execute(delete(NotificationJob).where(NotificationJob.anchor_id == anchor.id))
        await db.execute(delete(LiveSession).where(LiveSession.anchor_id == anchor.id))
        await db.execute(
            delete(UserSubscription).where(UserSubscription.anchor_id == anchor.id)
        )
        await db.execute(delete(PlatformAccount).where(PlatformAccount.anchor_id == anchor.id))
        await db.execute(delete(Anchor).where(Anchor.id == anchor.id))
        await db.commit()


def test_session_started_at():
    asyncio.run(_run())


if __name__ == "__main__":
    test_session_started_at()
    print("ALL SESSION STARTED_AT TESTS PASSED")
