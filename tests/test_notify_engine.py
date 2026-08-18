"""WeChat 通知引擎测试: grant 决策树 + 错误处理(mock 微信)。

覆盖 ROADMAP Gate 3 验收:
- grant 有余额 → 发送成功 consumed+1
- grant 无余额 → fallback in_app(reason=no_grant)
- 43101 → grant 失效 + fallback
- 45009 → 退避重试,grant 保留
- 40037 → 模板错误 + fallback
- delivery log 正确落库
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import (
    Anchor,
    LiveEvent,
    LiveSession,
    NotificationDelivery,
    NotificationJob,
    PlatformAccount,
    User,
    WechatSubscriptionGrant,
)
from workers.notify.wechat import get_or_create_grant, process_job

DB_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"
TEMPLATE = "test_template_001"
T0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)

CLEAN_TABLES = [
    "notification_deliveries", "notification_jobs", "live_events", "live_sessions",
    "user_subscriptions", "platform_accounts", "wechat_subscription_grants",
    "anchors", "users", "platform_health", "probe_runs",
]


class MockWeChat:
    """可配置返回值的 mock 微信客户端。"""

    def __init__(self, responses: list[dict] | None = None):
        self.responses = responses or [{"errcode": 0, "errmsg": "ok"}]
        self.call_count = 0
        self.last_payload = None

    def send_subscribe_message(self, openid, template_id, data, **kw):
        self.call_count += 1
        self.last_payload = data
        resp = self.responses[min(self.call_count - 1, len(self.responses) - 1)]
        return dict(resp)

    @staticmethod
    def build_live_start_payload(anchor_name, room_title, start_time, theme, activity="无"):
        return {
            "thing1": {"value": anchor_name[:20]},
            "thing2": {"value": room_title[:20]},
            "time3": {"value": start_time},
            "thing5": {"value": theme[:20]},
            "thing6": {"value": activity[:20]},
        }


async def clean(db: AsyncSession) -> None:
    for t in CLEAN_TABLES:
        await db.execute(text(f"DELETE FROM {t}"))


async def seed_job(db: AsyncSession, grant_count: int = 0) -> dict:
    """创建 user + anchor + pa + session + job。"""
    user = User(openid="openid_test_1", nickname="tester")
    db.add(user)
    await db.flush()

    anchor = Anchor(display_name="anchor_a")
    db.add(anchor)
    await db.flush()

    pa = PlatformAccount(
        anchor_id=anchor.id, platform="bilibili",
        platform_user_id="room_1",
        canonical_url="https://live.bilibili.com/1",
        last_status="ONLINE",
    )
    db.add(pa)
    await db.flush()

    session = LiveSession(
        platform_account_id=pa.id, anchor_id=anchor.id, platform="bilibili",
        started_at=T0, title="测试直播标题", state="OPEN",
    )
    db.add(session)
    await db.flush()

    event = LiveEvent(
        platform_account_id=pa.id, anchor_id=anchor.id, live_session_id=session.id,
        event_type="CONFIRMED_ONLINE", confidence="normal", detected_at=T0,
    )
    db.add(event)
    await db.flush()

    job = NotificationJob(
        live_event_id=event.id, live_session_id=session.id,
        user_id=user.id, anchor_id=anchor.id, state="PENDING",
    )
    db.add(job)
    await db.flush()

    if grant_count > 0:
        g = await get_or_create_grant(db, user.id, TEMPLATE)
        g.granted_count = grant_count
        g.consumed_count = 0
        await db.flush()

    return {"user": user, "job": job, "session": session}


async def test_send_success(db: AsyncSession) -> None:
    await clean(db)
    s = await seed_job(db, grant_count=1)
    mock = MockWeChat([{"errcode": 0, "errmsg": "ok", "msgid": "111"}])

    status = await process_job(db, s["job"], mock, TEMPLATE)
    assert status == "SENT"

    # consumed +1
    grant = await get_or_create_grant(db, s["user"].id, TEMPLATE)
    assert grant.consumed_count == 1
    assert grant.granted_count - grant.consumed_count == 0

    # delivery log
    d = (
        await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_job_id == s["job"].id
            )
        )
    ).scalar_one()
    assert d.channel == "wechat"
    assert d.state == "SENT"
    assert d.error_code is None

    # job DONE
    assert s["job"].state == "DONE"
    print("✓ 有 grant → 发送成功,consumed+1,delivery SENT")


async def test_no_grant_fallback(db: AsyncSession) -> None:
    await clean(db)
    s = await seed_job(db, grant_count=0)  # 无 grant
    mock = MockWeChat()

    status = await process_job(db, s["job"], mock, TEMPLATE)
    assert status == "FALLBACK_NO_GRANT"
    assert mock.call_count == 0  # 没调微信

    d = (
        await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_job_id == s["job"].id
            )
        )
    ).scalar_one()
    assert d.channel == "in_app"
    assert d.error_code == "no_grant"
    assert s["job"].state == "DONE"
    print("✓ 无 grant → 不调微信,fallback in_app(no_grant)")


async def test_43101_refused(db: AsyncSession) -> None:
    await clean(db)
    s = await seed_job(db, grant_count=1)
    mock = MockWeChat([{"errcode": 43101, "errmsg": "user refuse"}])

    status = await process_job(db, s["job"], mock, TEMPLATE)
    assert status == "FALLBACK_REFUSED"

    grant = await get_or_create_grant(db, s["user"].id, TEMPLATE)
    assert grant.consumed_count == 1  # grant 失效
    assert grant.granted_count - grant.consumed_count == 0

    # 两条 delivery: wechat FAILED + in_app SENT
    deliveries = (
        await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_job_id == s["job"].id
            )
        )
    ).scalars().all()
    channels = {(d.channel, d.state, d.error_code) for d in deliveries}
    assert ("wechat", "FAILED", "43101") in channels
    assert ("in_app", "SENT", "wx_43101") in channels
    assert s["job"].state == "DONE"
    print("✓ 43101 → grant 失效 + fallback in_app")


async def test_45009_retry_grant_kept(db: AsyncSession) -> None:
    await clean(db)
    s = await seed_job(db, grant_count=1)
    mock = MockWeChat([{"errcode": 45009, "errmsg": "rate limit"}])

    status = await process_job(db, s["job"], mock, TEMPLATE)
    assert status == "RETRY_45009"

    grant = await get_or_create_grant(db, s["user"].id, TEMPLATE)
    assert grant.consumed_count == 0  # grant 保留
    assert s["job"].state == "PENDING"  # 保持 PENDING 重试
    assert s["job"].attempt == 1
    print("✓ 45009 → 退避重试,grant 保留,job 仍 PENDING")


async def test_40037_template_invalid(db: AsyncSession) -> None:
    await clean(db)
    s = await seed_job(db, grant_count=1)
    mock = MockWeChat([{"errcode": 40037, "errmsg": "template invalid"}])

    status = await process_job(db, s["job"], mock, TEMPLATE)
    assert status == "TEMPLATE_DISABLED"

    grant = await get_or_create_grant(db, s["user"].id, TEMPLATE)
    assert grant.consumed_count == 0  # grant 保留(模板问题不是 grant 问题)

    deliveries = (
        await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_job_id == s["job"].id
            )
        )
    ).scalars().all()
    channels = {(d.channel, d.state, d.error_code) for d in deliveries}
    assert ("wechat", "FAILED", "40037") in channels
    assert ("in_app", "SENT", "wx_40037") in channels
    print("✓ 40037 → 模板错误,fallback in_app,grant 保留")


async def main() -> None:
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        await test_send_success(db)
        await test_no_grant_fallback(db)
        await test_43101_refused(db)
        await test_45009_retry_grant_kept(db)
        await test_40037_template_invalid(db)
        print("\n✓ 通知引擎 5 组测试全部通过(mock 微信)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
