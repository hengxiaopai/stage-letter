"""
Douyu 平台 Adapter — Gate 0B prototype

职责:解析 URL + 检测直播状态。不做调度、不持久化、不发送通知。

支持的 URL 形式:
- https://www.douyu.com/{room_id}
- https://www.douyu.com/{room_id}?xxx(带 query)
- 纯数字(斗鱼 room_id 一般是 6-9 位)

API:
- 桌面端:https://www.douyu.com/{room_id}
- HTML 内嵌 window.__INIT_STATE__ / window.$ROOM / 同类,含 show_status 字段
- 纯状态检测不需要签名(stream URL 才有)

字段映射(斗鱼惯例):
- show_status === 1  → 在播
- show_status === 2  → 未播
- videoLoop === 1    → 轮播(也算"在播")
- 兜底:扫描 HTML 找 "showStatus"|"show_status" 任意匹配
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

HOST = "https://www.douyu.com"


class DouyuAdapter:
    name = "douyu"

    def __init__(self, timeout: float = 8.0, min_interval: float = 2.0):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.douyu.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    # ---------- 限流 ----------
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_at = time.time()

    # ---------- URL 解析 ----------
    def parse_url(self, url: str) -> dict:
        if not url or not isinstance(url, str):
            raise ValueError(f"url 必须是非空字符串,got: {url!r}")
        url = url.strip()
        result = {"room_id": None, "raw": url}

        m = re.match(r"^https?://(?:www\.)?douyu\.com/(\d+)", url)
        if m:
            result["room_id"] = m.group(1)
            return result

        # 斗鱼 room_id 范围 1-12 位
        if re.match(r"^\d{1,12}$", url):
            result["room_id"] = url
            return result

        raise ValueError(f"无法解析斗鱼 URL: {url}")

    # ---------- HTML 抓取 + 状态解析 ----------
    def _fetch_html(self, room_id: str) -> dict:
        self._throttle()
        url = f"{HOST}/{room_id}"
        try:
            r = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            r.raise_for_status()
            return {"ok": True, "html": r.text, "url": r.url, "status": r.status_code}
        except requests.RequestException as e:
            logger.warning("斗鱼 HTML 抓取失败: %s, err=%s", url, e)
            return {"ok": False, "errcode": -1, "errmsg": str(e)}
        except ValueError as e:
            return {"ok": False, "errcode": -2, "errmsg": f"non-text: {e}"}

    def _parse_status_from_html(self, html: str) -> dict:
        """从 HTML 中识别直播状态

        策略(优先级):
        1. window.__INIT_STATE__ / window.$ROOM / window.DouyuData JSON 递归找 show_status
        2. 全文 grep 转义引号 + show_status(斗鱼 HTML 字段值是 \\"show_status\\":1)
        3. 全文 grep "showStatus"
        4. 全文 grep "isLiveBroadcast":true
        5. 全文 grep "videoLoop":1
        """
        # 策略 1:解析 window 全局变量
        for var in ("__INIT_STATE__", "$ROOM", "DouyuData", "HNF_GLOBAL_INIT", "__NUXT__"):
            m = re.search(
                rf'window\.{re.escape(var)}\s*=\s*(\{{.*?\}});',
                html,
                re.DOTALL,
            )
            if m:
                try:
                    data = json.loads(m.group(1))
                    status = self._find_live_status_in_obj(data)
                    if status is not None:
                        return {
                            "method": f"window_{var}",
                            "live": self._is_live_value(status),
                            "raw_status": status,
                        }
                except (json.JSONDecodeError, RecursionError, ValueError):
                    pass

        # 策略 2:show_status(转义或非转义引号都接受)
        m = re.search(r'\\?"show_status\\?"\s*:\s*(\d+)', html)
        if m:
            val = int(m.group(1))
            return {
                "method": "show_status_grep",
                "live": self._is_live_value(val),
                "raw_status": val,
            }

        # 策略 3:showStatus
        m = re.search(r'\\?"showStatus\\?"\s*:\s*("?)([12])\1', html)
        if m:
            val = int(m.group(2))
            return {
                "method": "showStatus_grep",
                "live": val == 1,
                "raw_status": val,
            }

        # 策略 4:isLiveBroadcast(斗鱼 SSR 字段,字符串 true/false)
        m = re.search(r'\\?"isLiveBroadcast\\?"\s*:\s*(true|false|"true"|"false")', html, re.IGNORECASE)
        if m:
            val = m.group(1).lower().strip('"')
            return {
                "method": "isLiveBroadcast_grep",
                "live": val == "true",
                "raw_status": val,
            }

        # 策略 5:videoLoop
        m = re.search(r'\\?"videoLoop\\?"\s*:\s*1\b', html)
        if m:
            return {"method": "videoLoop_grep", "live": True, "raw_status": "videoLoop=1"}

        return {"method": "none", "live": None, "raw_status": None}

    def _is_live_value(self, val) -> bool:
        """斗鱼 show_status 映射:1=在播, 2=未播, 其他(0/3/4)=未知"""
        if isinstance(val, bool):
            return val
        if isinstance(val, int):
            return val == 1
        if isinstance(val, str):
            return val in ("1", "true", "live")
        return False

    def _find_live_status_in_obj(self, obj, depth: int = 0) -> Optional[object]:
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower() if isinstance(k, str) else ""
                if kl in ("show_status", "showstatus", "livestatus", "isonlive", "islive"):
                    return v
                result = self._find_live_status_in_obj(v, depth + 1)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_live_status_in_obj(item, depth + 1)
                if result is not None:
                    return result
        return None

    def _find_start_time_in_obj(self, obj, depth: int = 0) -> Optional[object]:
        """递归搜索真实开播时间(斗鱼 start_time / roomStartTime, unix 秒)。

        2026-08-14 新增: session.started_at 必须取平台真实开播时间,
        不能用"探测到 ONLINE 的时刻"(主播可能已开播很久)。
        """
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower() if isinstance(k, str) else ""
                if kl in ("start_time", "roomstarttime", "live_start_time", "show_start_time"):
                    if isinstance(v, (int, float)) and v > 1000000000:
                        return v
                result = self._find_start_time_in_obj(v, depth + 1)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_start_time_in_obj(item, depth + 1)
                if result is not None:
                    return result
        return None

    # ---------- 统一入口 ----------
    def get_status(self, url: str) -> dict:
        """给定 URL,返回 7 态状态(见 state 字段)。"""
        # placeholder 短路
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
                "errcode": -4,
                "errmsg": str(e),
                "raw": url,
                "state": classify_error("douyu", -4, str(e)).value,
            }

        room_id = parsed["room_id"]
        fetch = self._fetch_html(room_id)
        if not fetch.get("ok"):
            errcode = fetch.get("errcode", -1)
            return {
                "ok": False,
                "errcode": errcode,
                "errmsg": fetch.get("errmsg", "fetch failed"),
                "room_id": room_id,
                "raw": url,
                "state": classify_error("douyu", errcode, fetch.get("errmsg", "")).value,
            }

        status = self._parse_status_from_html(fetch["html"])
        if status.get("live") is None:
            return {
                "ok": False,
                "errcode": -7,
                "errmsg": "no live status field found in HTML",
                "room_id": room_id,
                "parse_method": status.get("method"),
                "html_size": len(fetch["html"]),
                "raw": url,
                "state": LiveStatus.PARSE_ERROR.value,
            }

        # 2026-08-14: 真实开播时间($ROOM/__INIT_STATE__ JSON 优先, HTML grep 兜底)
        live_started_at = None
        try:
            for var in ("__INIT_STATE__", "$ROOM", "DouyuData", "HNF_GLOBAL_INIT", "__NUXT__"):
                m = re.search(
                    rf'window\.{re.escape(var)}\s*=\s*(\{{.*?\}});',
                    fetch["html"],
                    re.DOTALL,
                )
                if m:
                    data = json.loads(m.group(1))
                    st = self._find_start_time_in_obj(data)
                    if st:
                        live_started_at = int(st)
                        break
            if not live_started_at:
                m2 = re.search(r'\\?"(?:start_time|roomStartTime|liveStartTime)\\?"\s*:\s*(\d{10,})', fetch["html"])
                if m2:
                    live_started_at = int(m2.group(1))
        except Exception:
            pass

        # 斗鱼 raw_status 可能是 1/2(在播/未播)或 videoLoop=1 或 isLiveBroadcast=true
        raw = status["raw_status"]
        if isinstance(raw, bool):
            raw_normalized = 1 if raw else 2
        else:
            try:
                raw_normalized = int(raw)
            except (ValueError, TypeError):
                # videoLoop=1 / isLiveBroadcast=true 这类 → 视作 1
                raw_normalized = 1 if status.get("live") else 2

        return {
            "ok": True,
            "room_id": room_id,
            "live": bool(status["live"]),
            "raw_status": raw,
            "parse_method": status["method"],
            "html_size": len(fetch["html"]),
            "live_started_at": live_started_at,
            "state": classify_platform_status("douyu", raw_normalized).value,
        }

    def is_live(self, url: str) -> bool:
        s = self.get_status(url)
        return s.get("state") == LiveStatus.ONLINE.value


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python adapter.py <douyu_url_or_roomid>")
        print("Example: python adapter.py https://www.douyu.com/1")
        sys.exit(1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    a = DouyuAdapter()
    out = a.get_status(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
