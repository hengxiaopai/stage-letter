"""
Bilibili 平台 Adapter — Gate 0B prototype

职责:解析 URL + 检测直播状态。不做调度、不持久化、不发送通知。

支持的 URL 形式:
- https://space.bilibili.com/{uid}
- https://live.bilibili.com/{room_id}(含短号)
- 纯数字:优先按 uid 解析(更稳)

API 端点(均无鉴权):
- room_init?id=     → 短号转长号 + 状态
- getRoomInfoOld?mid= → uid 拿直播间 + 状态

live_status 含义:0=未直播, 1=直播中, 2=轮播

限流:B 站对未登录请求有 IP 级限流,默认 1s 间隔。生产环境需接入 REDIS 分布式限流(见 ARCHITECTURE.md)。
"""
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# 跨平台共享 7 态
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from platform_adapters.common import LiveStatus, classify_platform_status, classify_error, is_placeholder  # noqa: E402

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

API_BASE = "https://api.live.bilibili.com"


class BilibiliAdapter:
    name = "bilibili"

    def __init__(self, timeout: float = 5.0, min_interval: float = 1.0):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": UA, "Referer": "https://live.bilibili.com/"})

    # ---------- 限流 ----------
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_at = time.time()

    # ---------- URL 解析 ----------
    def parse_url(self, url: str) -> dict:
        """返回 {uid, room_id, raw}。三者至少有一个非空,否则抛 ValueError。"""
        if not url or not isinstance(url, str):
            raise ValueError(f"url 必须是非空字符串,got: {url!r}")
        url = url.strip()
        result = {"uid": None, "room_id": None, "raw": url}

        m = re.match(r"^https?://space\.bilibili\.com/(\d+)", url)
        if m:
            result["uid"] = int(m.group(1))
            return result

        m = re.match(r"^https?://live\.bilibili\.com/(\d+)", url)
        if m:
            result["room_id"] = int(m.group(1))
            return result

        m = re.match(r"^https?://(?:www\.)?bilibili\.com/(\d+)", url)
        if m:
            result["uid"] = int(m.group(1))
            return result

        if url.isdigit():
            result["uid"] = int(url)
            return result

        raise ValueError(f"无法解析 B 站 URL: {url}")

    # ---------- API 调用 ----------
    def _call(self, path: str, params: dict) -> dict:
        url = f"{API_BASE}{path}"
        self._throttle()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.warning("B 站 API 网络错误: %s, err=%s", url, e)
            return {"code": -1, "msg": f"network error: {e}", "data": None}
        except ValueError as e:
            logger.warning("B 站 API 返回非 JSON: %s, err=%s", url, e)
            return {"code": -2, "msg": f"non-json: {e}", "data": None}

    def fetch_by_room_id(self, room_id: int) -> dict:
        data = self._call("/room/v1/Room/room_init", {"id": room_id})
        if data.get("code") != 0 or not data.get("data"):
            errcode = data.get("code", -1)
            return {
                "ok": False,
                "errcode": errcode,
                "errmsg": data.get("msg", "unknown"),
                "room_id": room_id,
                "state": classify_error("bilibili", errcode, data.get("msg", "")).value,
            }
        d = data["data"]
        live_status = int(d.get("live_status", 0))
        live_time = int(d.get("live_time", 0))
        # 2026-08-14: 真实开播时间(unix 秒; B站对轮播/特殊房间可能返回 0 或负数垃圾值)
        # 仅接受合理 unix 时间戳(>2001-09-09), 否则视为未知
        live_started_at = live_time if live_time > 1000000000 else None
        return {
            "ok": True,
            "room_id": d.get("room_id"),
            "short_id": d.get("short_id"),
            "uid": d.get("uid"),
            "live_status": live_status,
            "title": d.get("title", ""),
            "live_time": live_time,
            "live_started_at": live_started_at,
            "is_portrait": bool(d.get("is_portrait", False)),
            "state": classify_platform_status("bilibili", live_status).value,
        }

    def fetch_by_uid(self, uid: int) -> dict:
        data = self._call("/room/v1/Room/getRoomInfoOld", {"mid": uid})
        if data.get("code") != 0 or not data.get("data"):
            errcode = data.get("code", -1)
            return {
                "ok": False,
                "errcode": errcode,
                "errmsg": data.get("msg", "unknown"),
                "uid": uid,
                "state": classify_error("bilibili", errcode, data.get("msg", "")).value,
            }
        d = data["data"]
        live_status = int(d.get("live_status", 0))
        live_time = int(d.get("live_time", 0))
        live_started_at = live_time if live_time > 1000000000 else None
        return {
            "ok": True,
            "room_id": d.get("roomid"),
            "uid": d.get("uid"),
            "title": d.get("title", ""),
            "live_status": live_status,
            "area_id": d.get("area_id"),
            "live_time": live_time,
            "live_started_at": live_started_at,
            "state": classify_platform_status("bilibili", live_status).value,
        }

    # ---------- 统一入口 ----------
    def get_status(self, url: str) -> dict:
        """给定 URL,返回 7 态状态(见 state 字段)。

        state ∈ ONLINE / OFFLINE / NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR / UNKNOWN
        """
        # placeholder 短路:不要拿 placeholder 去打 API
        if is_placeholder(url):
            return {
                "ok": False,
                "errcode": -100,
                "errmsg": "placeholder anchor not yet replaced by real room_id",
                "raw": url,
                "state": LiveStatus.NOT_FOUND.value,
            }
        try:
            parsed = self.parse_url(url)
        except ValueError as e:
            return {
                "ok": False,
                "errcode": -3,
                "errmsg": str(e),
                "raw": url,
                "state": classify_error("bilibili", -3, str(e)).value,
            }

        if parsed["room_id"] is not None:
            return self.fetch_by_room_id(parsed["room_id"])
        if parsed["uid"] is not None:
            return self.fetch_by_uid(parsed["uid"])
        return {
            "ok": False,
            "errcode": -2,
            "errmsg": "no uid or room_id parsed",
            "raw": url,
            "state": LiveStatus.UNKNOWN.value,
        }

    def is_live(self, url: str) -> bool:
        s = self.get_status(url)
        return s.get("state") == LiveStatus.ONLINE.value


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python adapter.py <bilibili_url_or_uid>")
        print("Example: python adapter.py https://space.bilibili.com/546195")
        sys.exit(1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    a = BilibiliAdapter()
    out = a.get_status(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
