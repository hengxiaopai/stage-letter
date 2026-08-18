"""
Huya 平台 Adapter — Gate 0B prototype

职责:解析 URL + 检测直播状态。不做调度、不持久化、不发送通知。

支持的 URL 形式:
- https://www.huya.com/{room_id}
- https://m.huya.com/{room_id}
- 纯数字(虎牙 room_id 一般是 4-10 位)

API:
- 移动端:https://m.huya.com/{room_id}
- 桌面端:https://www.huya.com/{room_id}
- HTML 内嵌 window.HNF_GLOBAL_INIT 或同类全局变量,含 liveStatus 字段
- 纯状态检测不需要签名(stream URL 才有签名挑战)

字段映射(虎牙 web 端惯例):
- liveStatus === true  → 在播
- liveStatus === false → 未播
- 不同版本字段名可能是 isOnLive / isLive / live_state
- 兜底:扫描 HTML 找 "isLive":true / "liveStatus":1 任意匹配
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

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Mobile/15E148 Safari/604.1"
)

MOBILE_HOST = "https://m.huya.com"


class HuyaAdapter:
    name = "huya"

    def __init__(self, timeout: float = 8.0, min_interval: float = 2.0):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": UA_MOBILE,
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

        m = re.match(r"^https?://(?:www\.|m\.)?huya\.com/(\d+)", url)
        if m:
            result["room_id"] = m.group(1)
            return result

        # 虎牙 room_id 范围很宽,1-15 位都接受
        if re.match(r"^\d{1,15}$", url):
            result["room_id"] = url
            return result

        raise ValueError(f"无法解析虎牙 URL: {url}")

    # ---------- HTML 抓取 + 状态解析 ----------
    def _fetch_html(self, room_id: str) -> dict:
        self._throttle()
        url = f"{MOBILE_HOST}/{room_id}"
        try:
            r = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            r.raise_for_status()
            return {"ok": True, "html": r.text, "url": r.url, "status": r.status_code}
        except requests.RequestException as e:
            logger.warning("虎牙 HTML 抓取失败: %s, err=%s", url, e)
            return {"ok": False, "errcode": -1, "errmsg": str(e)}
        except ValueError as e:
            return {"ok": False, "errcode": -2, "errmsg": f"non-text: {e}"}

    def _parse_status_from_html(self, html: str) -> dict:
        """从 HTML 中识别直播状态

        尝试多种策略,按优先级:
        1. body class liveStatus-on/off(桌面版权威信号)
        2. window.HNF_GLOBAL_INIT / __INIT_STATE__ JSON 递归找 eLiveStatus
        3. 全文 grep eLiveStatus 数字
        4. 全文 grep liveStatus 布尔/01
        5. 全文 grep isOnLive / isLive / live_state / isOn

        2026-08-14 P0-L1 修正: eLiveStatus 枚举实测
          eLiveStatus=2 ↔ body.liveStatus-on(直播中)
          eLiveStatus=1 ↔ body.liveStatus-off(未开播)
        旧代码 val in (1,2,3) 把 eLiveStatus=1(未开播) 误判为直播中
        → 姿态已下播但首页一直显示 LIVE(21h50m session 未关)。
        现在: 仅 eLiveStatus==2 视为直播中; 并优先用 body class 双信号交叉验证。
        """
        # 策略 0: body class(桌面版权威信号)
        m_body = re.search(r'<body[^>]*class="([^"]*)"', html)
        if m_body:
            cls = m_body.group(1)
            if "liveStatus-on" in cls:
                return {"method": "body_class", "live": True, "raw_status": "liveStatus-on"}
            if "liveStatus-off" in cls:
                return {"method": "body_class", "live": False, "raw_status": "liveStatus-off"}

        # 策略 1:HNF_GLOBAL_INIT
        m = re.search(
            r'window\.(?:HNF_GLOBAL_INIT|__INIT_STATE__|__NUXT__)\s*=\s*(\{.*?\});',
            html,
            re.DOTALL,
        )
        if m:
            try:
                blob = m.group(1)
                data = json.loads(blob)
                status = self._find_live_status_in_obj(data)
                if status is not None:
                    # eLiveStatus==2 才是直播中(1=未开播, 0/3 非直播)
                    live = (status == 2) if isinstance(status, int) else bool(status)
                    return {
                        "method": "hnf_global_init",
                        "live": live,
                        "raw_status": status,
                    }
            except (json.JSONDecodeError, RecursionError, ValueError):
                pass

        # 策略 2:eLiveStatus(2026-08-14 修正: 仅 2=直播中, 1=未开播)
        m = re.search(r'"eLiveStatus"\s*:\s*(\d+)', html)
        if m:
            val = int(m.group(1))
            return {
                "method": "eLiveStatus_grep",
                "live": val == 2,
                "raw_status": val,
            }

        # 策略 3:liveStatus
        m = re.search(r'"liveStatus"\s*:\s*("?)(true|false|1|0)\1', html, re.IGNORECASE)
        if m:
            val = m.group(2).lower()
            return {
                "method": "liveStatus_grep",
                "live": val in ("true", "1"),
                "raw_status": val,
            }

        # 策略 4:isOnLive / isLive
        m = re.search(r'"(isOnLive|isLive|live_state|isOn)"\s*:\s*("?)(true|false|1|0)\1', html, re.IGNORECASE)
        if m:
            val = m.group(3).lower()
            return {
                "method": f"{m.group(1)}_grep",
                "live": val in ("true", "1"),
                "raw_status": val,
            }

        return {"method": "none", "live": None, "raw_status": None}

    def _find_live_status_in_obj(self, obj, depth: int = 0) -> Optional[object]:
        """递归搜索直播状态字段(虎牙 eLiveStatus 优先,其他兼容)"""
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower() if isinstance(k, str) else ""
                if kl in ("elivestatus", "livestatus", "isonlive", "islive", "live_state"):
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
        """递归搜索真实开播时间字段(虎牙 startTime / start_time, unix 秒)。

        2026-08-14 新增: session.started_at 必须取平台真实开播时间,
        不能用"探测到 ONLINE 的时刻"(主播可能已开播很久)。
        """
        if depth > 6 or obj is None:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower() if isinstance(k, str) else ""
                if kl in ("starttime", "start_time", "live_start_time", "live_starttime", "start_time_show"):
                    # start_time_show 是友好字符串, 忽略; 只要数字时间戳
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
                "state": classify_error("huya", -4, str(e)).value,
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
                "state": classify_error("huya", errcode, fetch.get("errmsg", "")).value,
            }

        html = fetch["html"]
        status = self._parse_status_from_html(html)
        if status.get("live") is None:
            return {
                "ok": False,
                "errcode": -7,
                "errmsg": "no live status field found in HTML",
                "room_id": room_id,
                "parse_method": status.get("method"),
                "html_size": len(html),
                "raw": url,
                "state": LiveStatus.PARSE_ERROR.value,
            }

        # 2026-08-14: 真实开播时间(HNF_GLOBAL_INIT JSON 优先, HTML grep 兜底)
        live_started_at = None
        try:
            m = re.search(
                r'window\.(?:HNF_GLOBAL_INIT|__INIT_STATE__|__NUXT__)\s*=\s*(\{.*?\});',
                html,
                re.DOTALL,
            )
            if m:
                data = json.loads(m.group(1))
                st = self._find_start_time_in_obj(data)
                if st:
                    live_started_at = int(st)
            if not live_started_at:
                m2 = re.search(r'"(?:startTime|start_time|liveStartTime)"\s*:\s*(\d{10,})', html)
                if m2:
                    live_started_at = int(m2.group(1))
        except Exception:
            pass

        # 虎牙 raw_status 可能是 1/2/3 (在播) 或 0 (未播) 或 True/False
        raw = status["raw_status"]
        if isinstance(raw, bool):
            # HNF_GLOBAL_INIT 路径返回 bool,转 1/0
            raw_normalized = 1 if raw else 0
        else:
            try:
                raw_normalized = int(raw)
            except (ValueError, TypeError):
                raw_normalized = None

        return {
            "ok": True,
            "room_id": room_id,
            "live": bool(status["live"]),
            "raw_status": raw,
            "parse_method": status["method"],
            "html_size": len(html),
            "live_started_at": live_started_at,
            "state": classify_platform_status("huya", raw_normalized).value,
        }

    def is_live(self, url: str) -> bool:
        s = self.get_status(url)
        return s.get("state") == LiveStatus.ONLINE.value


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python adapter.py <huya_url_or_roomid>")
        print("Example: python adapter.py https://www.huya.com/1")
        sys.exit(1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    a = HuyaAdapter()
    out = a.get_status(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
