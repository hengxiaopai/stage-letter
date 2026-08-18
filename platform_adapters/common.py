"""
platform_adapters/common.py — 跨平台共享类型与 7 态分类器

StageLetter 的状态机不只有 ONLINE / OFFLINE,还包括 6 种"非直播"信号。
**禁止**把任何异常 / 错误 / 解析失败自动归为 OFFLINE(那是 silent parse failure)。

7 态定义:
- ONLINE:        平台侧明确表示在播(可触发开播事件)
- OFFLINE:       平台侧明确表示未播(可触发下播事件)
- NOT_FOUND:     房间不存在(404 / errcode 1 / 占位 ID)
- RATE_LIMITED:  触发了限流(HTTP 429 / 平台显式限流信号)
- BLOCKED:       触发了反爬(403 / cookie 失效 / 平台封禁)
- PARSE_ERROR:   抓到了响应但无法解析状态字段(HTML 结构变化)
- UNKNOWN:       其他无法归类的状态

⚠️ **已知语义边界(2026-08-02/04/06 实测)**:
B 站/虎牙/斗鱼的匿名持续轮询限流表现为**连接超时**(`HTTPSConnectionPool` 超时、
慢响应 150-300s),不是 HTTP 429。当前 errcode=-1 → PARSE_ERROR(保守归类)。
**Gate 0C 需做因果实验**决定是否把"连接超时且连续 N 次"升级为 RATE_LIMITED
(见 GATE-0.md Gate 0C C6)。在 Gate 0C 结论出来前,不要改 -1 的归类——
避免把真实网络错误误判为限流。

设计原则:
- 状态机 SUSPECT → CONFIRMED 二次确认仅对 ONLINE 转换生效,其余状态不下发
- PLACEHOLDER room_id 必须返回 NOT_FOUND,不得返回 OFFLINE
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class LiveStatus(str, Enum):
    """7 态状态机的统一枚举(字符串值便于 JSON 序列化)"""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    BLOCKED = "BLOCKED"
    PARSE_ERROR = "PARSE_ERROR"
    UNKNOWN = "UNKNOWN"


# 用于 24h 脚本的统计桶
ALL_STATES: list = [s.value for s in LiveStatus]

# Placeholder 检测(全大写英文,用户未替换的占位)
def is_placeholder(url_or_id: str) -> bool:
    if not isinstance(url_or_id, str):
        return False
    s = url_or_id.strip()
    return s.isupper() and "PLACEHOLDER" in s


def classify_platform_status(platform: str, raw_status: Any) -> LiveStatus:
    """根据不同平台的 raw status 值,映射到 7 态。

    仅在响应成功 + 已解析出 raw_status 时调用。
    raw_status 为 None / 不合法值时返回 UNKNOWN。
    """
    if raw_status is None:
        return LiveStatus.UNKNOWN

    s = str(raw_status).lower()

    if platform == "bilibili":
        # B 站:0=offline, 1=live, 2=轮播(算在播)
        if s in ("0", "false"):
            return LiveStatus.OFFLINE
        if s in ("1", "2", "true"):
            return LiveStatus.ONLINE
        return LiveStatus.UNKNOWN

    if platform == "douyin":
        # 抖音:0=offline, 2=live, 4=ended
        if s == "0":
            return LiveStatus.OFFLINE
        if s in ("2", "live"):
            return LiveStatus.ONLINE
        if s in ("4", "ended"):
            return LiveStatus.OFFLINE  # 已下播 → 视为 OFFLINE
        return LiveStatus.UNKNOWN

    if platform == "huya":
        # 虎牙 eLiveStatus(2026-08-14 实测修正):
        #   2 = 直播中(body.liveStatus-on); 1 = 未开播(body.liveStatus-off)
        #   0 = 未开播; 其他值(3 等) → UNKNOWN(不确定语义)
        # 旧惯例 "1/2/3 在播" 是错的 → 姿态已下播仍显示 LIVE 的根因
        try:
            n = int(s)
        except (ValueError, TypeError):
            return LiveStatus.UNKNOWN
        if n == 2:
            return LiveStatus.ONLINE
        if n in (0, 1):
            return LiveStatus.OFFLINE
        return LiveStatus.UNKNOWN

    if platform == "douyu":
        # 斗鱼:show_status 1=live, 2=offline, 0/其他=unknown
        try:
            n = int(s)
        except (ValueError, TypeError):
            return LiveStatus.UNKNOWN
        if n == 1:
            return LiveStatus.ONLINE
        if n == 2:
            return LiveStatus.OFFLINE
        return LiveStatus.UNKNOWN

    return LiveStatus.UNKNOWN


def classify_error(platform: str, errcode: Any, errmsg: str = "", http_status: Optional[int] = None) -> LiveStatus:
    """根据错误码 / HTTP 状态,映射到 7 态。

    用于 ok=False 的情况。
    """
    # HTTP 层
    if http_status is not None:
        if http_status == 429:
            return LiveStatus.RATE_LIMITED
        if http_status in (403, 451):
            return LiveStatus.BLOCKED
        if http_status == 404:
            return LiveStatus.NOT_FOUND

    try:
        ec = int(errcode) if errcode is not None else None
    except (ValueError, TypeError):
        ec = None

    msg = (errmsg or "").lower()

    if platform == "douyin":
        # 抖音:4001038=房间不存在 / "该内容暂时无法无法查看"
        if ec == 4001038 or "无法查看" in msg or "不存在" in msg:
            return LiveStatus.NOT_FOUND
        if ec in (40001, 42001):  # token 失效
            return LiveStatus.BLOCKED
        if ec in (-1, -2):  # 网络 / 解析
            return LiveStatus.PARSE_ERROR
        if ec == -4 or ec == -5 or ec == -6:  # URL 解析 / 短链展开
            return LiveStatus.NOT_FOUND
        if ec == -7:  # HTML 无状态字段(虎牙/斗鱼约定)
            return LiveStatus.PARSE_ERROR
        if ec == -3:  # 非 dict payload
            return LiveStatus.PARSE_ERROR

    if platform == "bilibili":
        # B 站:1=房间不存在, -1=网络, -2=非 JSON, -3=URL 解析, -7=HTML 无字段
        if ec == 1:
            return LiveStatus.NOT_FOUND
        if ec == -1:
            return LiveStatus.PARSE_ERROR  # 暂归 PARSE_ERROR(可能是限流,但需 Gate 0C 因果)
        if ec in (-2, -7):
            return LiveStatus.PARSE_ERROR
        if ec in (-3, -4):
            return LiveStatus.NOT_FOUND

    if platform == "huya":
        # 虎牙:-1=网络, -2=非 text, -4=URL 解析, -7=无状态字段
        if ec in (-1, -2):
            return LiveStatus.PARSE_ERROR
        if ec in (-4, -5, -6):
            return LiveStatus.NOT_FOUND
        if ec == -7:
            return LiveStatus.PARSE_ERROR

    if platform == "douyu":
        # 斗鱼:同虎牙
        if ec in (-1, -2):
            return LiveStatus.PARSE_ERROR
        if ec in (-4, -5, -6):
            return LiveStatus.NOT_FOUND
        if ec == -7:
            return LiveStatus.PARSE_ERROR

    # 兜底
    if ec is not None and ec < 0:
        return LiveStatus.PARSE_ERROR
    return LiveStatus.UNKNOWN
