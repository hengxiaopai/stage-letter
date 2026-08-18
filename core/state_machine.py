"""状态机: OFFLINE → SUSPECT_ONLINE → ONLINE → SUSPECT_OFFLINE → OFFLINE(抗抖动)。

设计来源: ARCHITECTURE.md §状态机。SUSPECT 中间态防止单次探测抖动造成误报。

规则(与 PLATFORM-ADAPTER-SPEC §7 一致):
- OFFLINE + probe=ONLINE  → SUSPECT_ONLINE
- SUSPECT_ONLINE + probe=ONLINE → CONFIRMED_ONLINE(触发开播事件)
- SUSPECT_ONLINE + probe=OFFLINE → 回到 OFFLINE(抖动,不触发事件)
- ONLINE + probe=OFFLINE → SUSPECT_OFFLINE
- SUSPECT_OFFLINE + probe=OFFLINE → CONFIRMED_OFFLINE(触发下播事件)
- SUSPECT_OFFLINE + probe=ONLINE → 回到 ONLINE(抖动)
"""
from __future__ import annotations

from core.models import LiveStatus

# 需要几次连续相同探测才确认转换(抗抖动窗口)
CONFIRM_WINDOW = 2


def transition(current: str, probe_status: str) -> dict:
    """根据当前状态 + 单次探测结果,返回 {new_state, event_type|None}。

    Args:
        current: platform_accounts.last_status(ONLINE/OFFLINE/SUSPECT_ONLINE/SUSPECT_OFFLINE)
        probe_status: adapter 返回的 7 态

    Returns:
        {"state": new_state, "event": event_type_or_None}
    """
    # 非 ONLINE/OFFLINE 的探测(限流/被墙/解析错误)不触发状态转换
    if probe_status not in (LiveStatus.ONLINE.value, LiveStatus.OFFLINE.value):
        return {"state": current, "event": None}

    online = probe_status == LiveStatus.ONLINE.value

    if current == LiveStatus.OFFLINE.value:
        if online:
            return {"state": LiveStatus.SUSPECT_ONLINE.value, "event": "SUSPECT_ONLINE"}
        return {"state": current, "event": None}

    if current == LiveStatus.SUSPECT_ONLINE.value:
        if online:
            return {"state": LiveStatus.ONLINE.value, "event": "CONFIRMED_ONLINE"}
        return {"state": LiveStatus.OFFLINE.value, "event": None}

    if current == LiveStatus.ONLINE.value:
        if not online:
            return {"state": LiveStatus.SUSPECT_OFFLINE.value, "event": "SUSPECT_OFFLINE"}
        return {"state": current, "event": None}

    if current == LiveStatus.SUSPECT_OFFLINE.value:
        if not online:
            return {"state": LiveStatus.OFFLINE.value, "event": "CONFIRMED_OFFLINE"}
        return {"state": LiveStatus.ONLINE.value, "event": None}

    # 未知状态 → 保持
    return {"state": current, "event": None}
