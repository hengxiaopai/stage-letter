"""Probe Worker(Gate 2 Detection Engine)。

职责:
1. 从 platform_accounts 表选出 due 的账号(按 polling_tier 分级轮询)
2. 用对应平台 adapter 调 get_status(canonical_url)
3. 把 7 态结果喂给 LiveSessionEngine.on_probe(状态机 + 去重 + fan-out)
4. 更新 platform_health(成功/失败计数 + 熔断降级)
5. 每平台限流器(aiolimiter)控制请求速率
6. probe_runs telemetry 持续写入(审计)

分级轮询(ARCHITECTURE §5.4):
- hot:  轮询间隔短(如 60s)  — 高价值主播
- warm: 轮询间隔中(如 300s) — 默认
- cold: 轮询间隔长(如 900s) — 低频主播

熔断降级(Gate 2 验收):
- 连续 5 次失败 → platform_health.state = DEGRADED
- DEGRADED 状态: 探测频率降到 1/5,事件仍写但 confidence='low'
- 连续 20 次失败 → DISABLED(停止探测,人工恢复)

用法:
    python -m workers.probe.worker --loop --interval 30
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

from aiolimiter import AsyncLimiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from core.live_session_engine import LiveSessionEngine
from core.models import PlatformAccount, PlatformHealth, ProbeRun

logger = logging.getLogger("stageletter.probe")

# tier → 轮询间隔秒
# P0-L3: 小规模阶段高频轮询(warm 300→60s), 状态新鲜度优先;
# 规模上来后再做冷热分层(hot=30 / warm=60 / cold=300)
# 用户已订阅主播优先保证新鲜度：在小规模阶段，在线 15 秒、离线 30 秒
# 可在不超过各平台保护节奏的前提下给出明显更快的状态反馈。
TIER_INTERVALS = {"hot": 15, "warm": 30, "cold": 180}

# 每平台最大并发探测
PLATFORM_MAX_CONCURRENCY = 3

# 熔断阈值
DEGRADED_THRESHOLD = 5   # 连续失败次数 → DEGRADED
DISABLE_THRESHOLD = 20   # 连续失败次数 → DISABLED

# DEGRADED 状态下的探测间隔倍率(降频)
DEGRADED_INTERVAL_MULT = 5

# 平台 → adapter 类
ADAPTERS: dict[str, type] = {}

# Provider session/cookie is intentionally process-scoped. Recreating a Douyin
# adapter per account re-fetches ttwid and turns a six-account refresh into six
# slow bootstrap requests; the platform limiter serializes access so reuse is
# safe for the synchronous adapters in this worker.
_ADAPTER_INSTANCES: dict[str, object] = {}


def _load_adapters() -> None:
    global ADAPTERS
    import platform_adapters.bilibili.adapter as b
    import platform_adapters.douyin.adapter as d
    import platform_adapters.douyu.adapter as du
    import platform_adapters.huya.adapter as h

    for mod, name in (
        (b, "bilibili"),
        (d, "douyin"),
        (du, "douyu"),
        (h, "huya"),
    ):
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if isinstance(cls, type) and hasattr(cls, "get_status") and "Adapter" in attr:
                ADAPTERS[name] = cls
                break


# 每平台限流器(启动时按已知平台建)
_LIMITERS: dict[str, AsyncLimiter] = {}

# 项目内的保护阈值，不是平台公开配额声明。抖音适配器自身建议 3 秒最小间隔；
# worker 在每次 probe 新建 adapter，因此必须在这里保持跨账号、跨 adapter 的节流。
PLATFORM_MIN_INTERVAL_S = {
    "douyin": 3.0,
    "bilibili": 1.0,
    "douyu": 2.0,
    "huya": 2.0,
}

# 每平台健康度缓存(进程内,避免每账号查 DB)
_HEALTH_CACHE: dict[str, dict] = {}


def get_limiter(platform: str) -> AsyncLimiter:
    """跨账号平台限流器，遵守本项目的保守访问间隔。"""
    if platform not in _LIMITERS:
        _LIMITERS[platform] = AsyncLimiter(
            1, PLATFORM_MIN_INTERVAL_S.get(platform, 1.0)
        )
    return _LIMITERS[platform]


async def pick_due_accounts(
    db: AsyncSession, now: datetime, batch: int = 50
) -> list[PlatformAccount]:
    """选出 due 的账号(未禁用 + 超过轮询间隔,含 DEGRADED 降频)。"""
    due = []
    health = {
        h.platform: h for h in
        (await db.execute(select(PlatformHealth))).scalars().all()
    }
    for pa in (
        await db.execute(
            select(PlatformAccount).where(PlatformAccount.is_disabled.is_(False))
        )
    ).scalars().all():
        # 状态翻转后的二次确认走高优先级节奏，避免用户长时间等待。
        if pa.last_status in ("SUSPECT_ONLINE", "SUSPECT_OFFLINE"):
            interval = 8
        else:
            interval = TIER_INTERVALS.get(pa.polling_tier, 300)
            # ONLINE 优先 15s；已订阅但离线的主播维持 30s。
            if pa.last_status == "ONLINE":
                interval = min(interval, 15)
            elif pa.last_status == "OFFLINE":
                interval = min(interval, 30)
        # DEGRADED 平台降频
        hp = health.get(pa.platform)
        if hp and hp.state == "DEGRADED":
            interval *= DEGRADED_INTERVAL_MULT
        if hp and hp.state == "DISABLED":
            continue  # DISABLED 平台不探测
        if pa.last_probe_at is None:
            due.append(pa)
        elif now - pa.last_probe_at >= timedelta(seconds=interval):
            due.append(pa)
        if len(due) >= batch:
            break
    return due


async def probe_one(
    db: AsyncSession, pa: PlatformAccount, engine: LiveSessionEngine
) -> None:
    """探测单个账号并更新状态/健康度。"""
    adapter_cls = ADAPTERS.get(pa.platform)
    if adapter_cls is None:
        logger.warning("pa=%s 平台 %s 无 adapter", pa.id, pa.platform)
        return

    now = datetime.now(timezone.utc)
    probe_start = time.monotonic()
    limiter = get_limiter(pa.platform)

    try:
        # 限流: 每平台令牌桶
        async with limiter:
            # adapter 是同步代码(requests,含构造函数里的 ttwid 获取)。
            # 复用平台会话以避免每个账号重复 bootstrap cookie；限流器保证
            # 同一平台只有一个调用在途。
            adapter = _ADAPTER_INSTANCES.get(pa.platform)
            if adapter is None:
                adapter = await asyncio.to_thread(adapter_cls)
                _ADAPTER_INSTANCES[pa.platform] = adapter
            result = await asyncio.to_thread(adapter.get_status, pa.canonical_url)

        latency_ms = int((time.monotonic() - probe_start) * 1000)
        state = result.get("state", "UNKNOWN")
        meta = {
            "room_id": str(result["room_id"]) if result.get("room_id") else None,
            "title": result.get("title"),
            "cover": result.get("cover"),
            "viewer_count": result.get("viewer_count") or result.get("user_count"),
            "source": result.get("source") or f"{pa.platform}.adapter",
            # 2026-08-14: 平台真实开播时间(unix 秒) — engine 建 session 用它而非探测时刻
            "live_started_at": result.get("live_started_at"),
            "raw": {k: v for k, v in result.items() if k not in ("state",)},
        }

        # DEGRADED 平台事件标 low confidence
        confidence = "low" if (await _is_degraded(db, pa.platform)) else "normal"
        if confidence == "low":
            meta["_confidence"] = "low"

        # 喂给状态机引擎
        await engine.on_probe(pa.id, state, meta, now=now)

        # P0: 状态新鲜度字段
        #   last_probe_at: 任何探测执行(证明心跳活着)
        #   last_successful_probe_at + failures: 可信探测才清零失败计数
        pa.last_probe_at = now
        if state in ("ONLINE", "OFFLINE", "NOT_FOUND"):
            pa.last_successful_probe_at = now
            pa.consecutive_probe_failures = 0
        else:
            pa.consecutive_probe_failures = (pa.consecutive_probe_failures or 0) + 1
        await db.flush()

        # 健康度: 成功
        await _health(db, pa.platform, success=True, latency_ms=latency_ms)
        # telemetry
        await _record_probe_run(db, pa, success=True, latency_ms=latency_ms, state=state)
        logger.info("pa=%s %s → %s (%dms)", pa.id, pa.canonical_url, state, latency_ms)
    except Exception as e:
        latency_ms = int((time.monotonic() - probe_start) * 1000)
        logger.error("pa=%s 探测失败: %s", pa.id, e)
        await _health(db, pa.platform, success=False, latency_ms=latency_ms)
        await _record_probe_run(db, pa, success=False, latency_ms=latency_ms, error=str(e)[:200])


async def _is_degraded(db: AsyncSession, platform: str) -> bool:
    hp = await db.get(PlatformHealth, platform)
    return hp is not None and hp.state in ("DEGRADED", "DISABLED")


async def _health(
    db: AsyncSession, platform: str, success: bool, latency_ms: int | None
) -> None:
    """更新 platform_health(含熔断降级)。"""
    hp = await db.get(PlatformHealth, platform)
    now = datetime.now(timezone.utc)
    if hp is None:
        hp = PlatformHealth(
            platform=platform,
            success_count_24h=1 if success else 0,
            error_count_24h=0 if success else 1,
            consecutive_failures=0 if success else 1,
            last_success_at=now if success else None,
            last_failure_at=None if success else now,
        )
        db.add(hp)
        await db.flush()
    else:
        if success:
            hp.success_count_24h += 1
            hp.consecutive_failures = 0
            hp.last_success_at = now
            if hp.state == "DEGRADED":
                # 连续成功后恢复
                hp.state = "HEALTHY"
                logger.info("平台 %s 恢复 HEALTHY", platform)
        else:
            hp.error_count_24h += 1
            hp.consecutive_failures += 1
            hp.last_failure_at = now
            if hp.consecutive_failures >= DISABLE_THRESHOLD:
                hp.state = "DISABLED"
                logger.error("平台 %s 连续 %d 次失败 → DISABLED(需人工恢复)", platform, hp.consecutive_failures)
            elif hp.consecutive_failures >= DEGRADED_THRESHOLD:
                hp.state = "DEGRADED"
                logger.warning("平台 %s 连续 %d 次失败 → DEGRADED(降频,事件标 low confidence)", platform, hp.consecutive_failures)


async def _record_probe_run(
    db: AsyncSession,
    pa: PlatformAccount,
    success: bool,
    latency_ms: int,
    state: str | None = None,
    error: str | None = None,
) -> None:
    """probe_runs telemetry(审计用,轻量写入)。"""
    pr = ProbeRun(
        platform_account_id=pa.id,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        success=success,
        error_message=error,
        snapshot={"state": state, "latency_ms": latency_ms},
    )
    db.add(pr)


async def run_once(db: AsyncSession, engine: LiveSessionEngine) -> int:
    """跑一轮探测,返回探测数。"""
    now = datetime.now(timezone.utc)
    accounts = await pick_due_accounts(db, now)
    for pa in accounts:
        await probe_one(db, pa, engine)
        await db.commit()  # 每账号提交,避免长事务
    # P0-LiveTruth: worker 心跳(健康检查)
    from core.health import worker_heartbeat
    worker_heartbeat(accounts_probed=len(accounts))
    return len(accounts)


async def loop(interval_s: int) -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _load_adapters()
    logger.info("Probe worker 启动(适配器: %s)", list(ADAPTERS.keys()))

    while True:
        try:
            async with factory() as db:
                le = LiveSessionEngine(db)
                n = await run_once(db, le)
                if n:
                    logger.info("本轮探测 %d 个账号", n)
        except Exception as e:
            logger.error("worker 循环异常: %s", e)
        await asyncio.sleep(interval_s)


async def once() -> int:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _load_adapters()
    async with factory() as db:
        le = LiveSessionEngine(db)
        n = await run_once(db, le)
        logger.info("单轮探测完成: %d 个账号", n)
        return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true", help="持续循环(默认单轮)")
    ap.add_argument("--interval", type=int, default=30, help="循环间隔秒(默认 30)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.loop:
        asyncio.run(loop(args.interval))
    else:
        asyncio.run(once())


if __name__ == "__main__":
    main()
