"""系统健康检查路由(P0-LiveTruth-02)。

GET /api/v1/system/health → {
    api: HEALTHY,
    worker: {healthy, last_tick_at, age_s, accounts_probed},
    douyin: {login_state, degraded},
    timestamp
}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.health import get_health
from core.models import PlatformHealth

router = APIRouter()


async def build_system_health(db: AsyncSession) -> dict:
    """Build one shared operational snapshot for public health and protected Admin."""
    h = get_health()

    # 平台健康度(DB)
    healths = (await db.execute(select(PlatformHealth))).scalars().all()
    platforms = {}
    for ph in healths:
        platforms[ph.platform] = {
            "state": ph.state,
            "consecutive_failures": ph.consecutive_failures,
            "success_count_24h": ph.success_count_24h,
            "error_count_24h": ph.error_count_24h,
            "last_success_at": ph.last_success_at.isoformat() if ph.last_success_at else None,
            "last_failure_at": ph.last_failure_at.isoformat() if ph.last_failure_at else None,
            "avg_latency_ms_24h": ph.avg_latency_ms_24h,
        }
    h["platforms"] = platforms

    # 抖音登录态(文件状态)
    try:
        from api.services.douyin_session import login_status
        ls = login_status()
        h["douyin"] = {
            "login_state": "LOGGED_IN" if ls.get("logged_in") else "AUTH_REQUIRED",
            "stale": ls.get("stale"),
            "error": ls.get("error"),
            "checked_at": ls.get("checked_at"),
        }
    except Exception as e:
        h["douyin"] = {"login_state": "UNKNOWN", "error": str(e)[:60]}

    from datetime import datetime, timezone
    h["timestamp"] = datetime.now(timezone.utc).isoformat()
    return h


@router.get("/system/health")
async def system_health(
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await build_system_health(db)
