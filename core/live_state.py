"""统一 Current Live State — P0-L1/L2/L3 状态真相链核心。

所有消费方(首页 / 订阅页 / 详情页 / 搜索结果)必须读这个函数的结果,
禁止各自从 last_status 直接推断。

语义(用户 P0-L3 要求):
- fresh + ONLINE          → {state: "LIVE",      is_live: True}
- fresh + OFFLINE         → {state: "OFFLINE",   is_live: False}
- fresh + UNKNOWN/其他    → {state: "UNKNOWN",   is_live: None}
- stale(超过阈值未探测)    → {state: "CONFIRMING", is_live: None, freshness: "stale"}
                            ↑ 不再断言"直播中/等待开播", UI 显示"状态确认中"

阈值:
- 默认 STALE_AFTER_S = 90 (90s 未探测 → stale)
- worker 小规模阶段 warm=60s 轮询, 正常情况永远 fresh
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 探测超过该秒数未更新 → stale
STALE_AFTER_S = 90

# stale 超过该秒数 → 不再"确认中", 回退 UNKNOWN(状态未知·检测失败)
# P0-L4: 防止主播无限期停留在中间态(用户反馈 3 位主播长期"状态确认中")
CONFIRM_TIMEOUT_S = 600  # 10 分钟

# 连续不可信探测次数达到该值 → DEGRADED(平台检测能力异常)
DEGRADED_FAILURES = 5

# 结果语义
FRESH = "fresh"
STALE = "stale"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def current_live_state(
    last_status: str | None,
    last_successful_probe_at: datetime | None,
    now: datetime | None = None,
    stale_after_s: int = STALE_AFTER_S,
    confirm_timeout_s: int = CONFIRM_TIMEOUT_S,
    heartbeat_at: datetime | None = None,
    consecutive_failures: int = 0,
) -> dict:
    """根据 DB 的 last_status + 探测时间戳计算统一当前状态(P0 唯一映射)。

    参数:
      last_status: DB 状态(ONLINE/OFFLINE/SUSPECT_*/UNKNOWN/...)
      last_successful_probe_at: 最近可信探测时间(新鲜度依据)
      heartbeat_at: 最近任何探测时间(心跳可见性, 与状态判断无关)
      consecutive_failures: 连续不可信探测次数(>DEGRADED_FAILURES → DEGRADED)

    Live State → UI 唯一映射(P0):
      LIVE       → 正在直播(+liveCount, 仅 ONLINE_CONFIRMED+fresh)
      OFFLINE    → 未开播/等待开播
      CONFIRMING → 状态确认中(过渡态, 有超时)
      UNKNOWN    → 暂时无法确认状态(探测失败/超时回退)
      DEGRADED   → 平台检测能力异常(连续失败)

    Returns:
        {
            "state": "LIVE" | "OFFLINE" | "CONFIRMING" | "UNKNOWN" | "DEGRADED",
            "is_live": True | False | None,
            "freshness": "fresh" | "stale" | "never",
            "last_probe_at": iso | None,          # 最近任何探测(心跳)
            "last_successful_probe_at": iso | None,
            "consecutive_probe_failures": int,
            "stale_after_s": int,
        }
    """
    now = now or now_utc()

    # DEGRADED: 连续不可信探测超阈值 → 平台检测能力异常(优先于状态推断)
    if consecutive_failures >= DEGRADED_FAILURES:
        return {
            "state": "DEGRADED",
            "is_live": None,
            "freshness": STALE,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat() if last_successful_probe_at else None,
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    # 从未可信探测过 → 无法断言任何状态
    if last_successful_probe_at is None:
        return {
            "state": "CONFIRMING" if last_status == "ONLINE" else "UNKNOWN",
            "is_live": None,
            "freshness": "never",
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": None,
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    # 时间戳规范化(naive → UTC)
    if last_successful_probe_at.tzinfo is None:
        last_successful_probe_at = last_successful_probe_at.replace(tzinfo=timezone.utc)

    age_s = (now - last_successful_probe_at).total_seconds()

    # stale 语义(P0-L4 回退机制):
    #   ≤ stale_after_s        → fresh, 按 last_status 断言
    #   stale_after_s < age ≤ confirm_timeout → CONFIRMING(状态确认中, 过渡态)
    #   age > confirm_timeout  → UNKNOWN(检测失败, 不再无限"确认中")
    if age_s > confirm_timeout_s:
        return {
            "state": "UNKNOWN",
            "is_live": None,
            "freshness": STALE,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat(),
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    stale = age_s > stale_after_s

    # stale(过渡期): 状态可能已过期 → 显示"状态确认中", 不断言
    if stale:
        return {
            "state": "CONFIRMING",
            "is_live": None,
            "freshness": STALE,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat(),
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    # fresh: 按 last_status 断言
    if last_status == "ONLINE":
        return {
            "state": "LIVE",
            "is_live": True,
            "freshness": FRESH,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat(),
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }
    if last_status == "OFFLINE":
        return {
            "state": "OFFLINE",
            "is_live": False,
            "freshness": FRESH,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat(),
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    # 其他(SUSPECT_ONLINE/SUSPECT_OFFLINE/NOT_FOUND/UNKNOWN/BLOCKED...)
    # SUSPECT 中间态 → 抗抖动窗口, UI 显示"确认中"
    if last_status in ("SUSPECT_ONLINE", "SUSPECT_OFFLINE"):
        return {
            "state": "CONFIRMING",
            "is_live": None,
            "freshness": FRESH,
            "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "last_successful_probe_at": last_successful_probe_at.isoformat(),
            "consecutive_probe_failures": consecutive_failures,
            "stale_after_s": stale_after_s,
        }

    return {
        "state": "UNKNOWN",
        "is_live": None,
        "freshness": FRESH,
        "last_probe_at": heartbeat_at.isoformat() if heartbeat_at else None,
        "last_successful_probe_at": last_successful_probe_at.isoformat(),
        "consecutive_probe_failures": consecutive_failures,
        "stale_after_s": stale_after_s,
    }


def is_confirmed_live(ls: dict) -> bool:
    """是否已确认直播中(仅 fresh + LIVE)。"""
    return ls.get("state") == "LIVE" and ls.get("freshness") == FRESH


def from_platform_account(pa) -> dict:
    """从 PlatformAccount ORM 对象计算统一 Current Live State(P0 唯一入口)。

    所有 API(首页/订阅/详情/搜索)必须走这里, 禁止各自用 last_status 推断。
    """
    return current_live_state(
        pa.last_status,
        pa.last_successful_probe_at or pa.last_checked_at,
        heartbeat_at=pa.last_probe_at,
        consecutive_failures=pa.consecutive_probe_failures or 0,
    )
