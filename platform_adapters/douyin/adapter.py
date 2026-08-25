"""
Douyin 平台 Adapter — Gate 0B prototype

职责:解析 URL + 检测直播状态。不做调度、不持久化、不发送通知。

支持的 URL 形式:
- https://v.douyin.com/{short_id}    (短链,会 302 跳转)
- https://www.douyin.com/live/{room_id}
- https://live.douyin.com/{room_id}
- 纯 19 位数字:按 room_id 解析

API:
- 探活端点:https://live.douyin.com/webcast/room/web/enter/?aid=6383&web_rid={id}
- 需要 ttwid cookie(首次访问 live.douyin.com 根路径会下发)
- 状态码:0=未开播, 2=直播中, 4=已结束(永久)

反爬说明:
- 抖音 web API 对匿名请求基本 401,必须先获取 ttwid
- 字段名(status / status_str)随版本会变,adapter 保留 status_str 作为 fallback
- ttwid 有效期 ~14 天,生产环境需在 cookie 失效时自动续期(见 §2)
"""
import asyncio
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

WEB_ROOT = "https://live.douyin.com"
ENTER_API = (
    f"{WEB_ROOT}/webcast/room/web/enter/"
    "?aid=6383&app_name=douyin_web&live_id=1"
    "&device_platform=web&language=zh-CN"
    "&enter_from=link_share&cookie_enabled=true"
    "&screen_width=1280&screen_height=720"
    "&browser_language=zh-CN&browser_platform=Win32"
    "&browser_name=Mozilla&browser_version=124.0.0.0"
)

# 状态码映射
LIVE_STATUS_MAP = {0: "offline", 2: "live", 4: "ended"}


class DouyinAdapter:
    name = "douyin"

    def __init__(self, timeout: float = 8.0, min_interval: float = 3.0):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": UA,
            "Referer": "https://live.douyin.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self._ttwid: Optional[str] = None
        self._init_ttwid()

    # ---------- ttwid 获取 ----------
    def _init_ttwid(self) -> None:
        """首次访问根域名拿 ttwid cookie(抖音必须)"""
        try:
            r = self._session.get(WEB_ROOT, timeout=self.timeout, allow_redirects=True)
            ttwid = self._session.cookies.get("ttwid")
            if ttwid:
                self._ttwid = ttwid
                logger.info("已获取 ttwid: %s...", ttwid[:12])
            else:
                logger.warning("未拿到 ttwid,web API 可能被拒")
        except Exception as e:
            logger.warning("初始化 ttwid 失败: %s", e)

    def _ensure_ttwid(self) -> None:
        if not self._ttwid:
            self._init_ttwid()

    # ---------- 限流 ----------
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_at = time.time()

    # ---------- URL 解析 ----------
    def parse_url(self, url: str) -> dict:
        """返回 {room_id, raw, expanded_url, needs_redirect}"""
        if not url or not isinstance(url, str):
            raise ValueError(f"url 必须是非空字符串,got: {url!r}")
        url = url.strip()
        result = {"room_id": None, "raw": url, "expanded_url": None, "needs_redirect": False}

        # 1. 短链
        if re.match(r"^https?://v\.douyin\.com/", url):
            result["needs_redirect"] = True
            return result

        # 2. 长链 live 页
        m = re.match(r"^https?://(?:www\.)?douyin\.com/live/(\d+)", url)
        if m:
            result["room_id"] = m.group(1)
            return result

        m = re.match(r"^https?://live\.douyin\.com/(\d+)", url)
        if m:
            result["room_id"] = m.group(1)
            return result

        # 2.5 user 主页(douyin.com/user/{sec_uid})
        # 2026-08-13 P0-Audit: 订阅的抖音主播都是 user 主页链接, 之前无法解析 → NOT_FOUND 误导
        # user 主页无 room_id, 未登录无法探测 live 状态 → get_status 走 UNKNOWN 分支
        m = re.match(r"^https?://(?:www\.)?douyin\.com/user/([A-Za-z0-9_\-]+)", url)
        if m:
            result["user_id"] = m.group(1)
            result["room_id"] = None
            result["is_user_page"] = True
            return result

        # 3. 纯数字 web_rid(12 位左右;也兼容 19 位内部 room_id)
        if re.match(r"^\d{10,25}$", url):
            result["room_id"] = url
            return result

        raise ValueError(f"无法解析抖音 URL: {url}")

    def _expand_short_url(self, url: str) -> Optional[str]:
        """展开短链 v.douyin.com/xxx → 真实 live URL"""
        try:
            r = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            return r.url
        except Exception as e:
            logger.warning("展开短链失败: %s, err=%s", url, e)
            return None

    def _extract_room_id_from_url(self, url: str) -> Optional[str]:
        m = re.search(r"/live/(\d{10,25})", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _probe_profile_via_streamget(sec_uid: str) -> dict:
        """Resolve a stable Douyin profile identity without browser signing.

        The signed web ``profile/other`` route is useful when it is available,
        but it must not be the only way to inspect a subscribed creator.  The
        formal StreamGet gateway already accepts the canonical ``sec_uid`` and
        exposes explicit room status.  Keep the old status contract here so
        Gate 0B callers can consume the result without importing formal types.
        """
        from stage_letter.infrastructure.platforms.douyin_streamget import (
            StreamGetDouyinGateway,
        )

        record = asyncio.run(StreamGetDouyinGateway().fetch_live(sec_uid))
        raw_status = record.raw_status
        if raw_status == 2:
            state = LiveStatus.ONLINE.value
        elif raw_status == 4:
            state = LiveStatus.OFFLINE.value
        else:
            state = LiveStatus.UNKNOWN.value
        return {
            "ok": state != LiveStatus.UNKNOWN.value,
            "room_id": record.room_id,
            "nickname": None,
            "title": record.title,
            "raw_status": raw_status,
            "source": record.source,
            "state": state,
        }

    # ---------- API 调用 ----------
    def _fetch_status(self, web_rid: str) -> dict:
        self._ensure_ttwid()
        self._throttle()
        try:
            r = self._session.get(
                ENTER_API,
                params={"web_rid": web_rid},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.warning("抖音 enter API 失败: web_rid=%s, err=%s", web_rid, e)
            return {"status_code": -1, "data": None}
        except ValueError as e:
            logger.warning("抖音 enter 返回非 JSON: web_rid=%s, err=%s", web_rid, e)
            return {"status_code": -2, "data": None}

    def _parse_status_payload(self, payload: dict) -> dict:
        """解析新版 enter API 响应(2026-08-06 实测改版)。

        新版结构(2026-08-06 浏览器实测):
        - status_code: 0=成功, 4001038=房间不存在(NOT_FOUND)
        - data.room_status: 房间可进入状态(0=可进入;非权威直播状态)
        - data.enter_room_id: 进入的房间内部 ID(19 位 id_str)
        - data.data[0]: 房间详情(旧版 data.room 移到这里)
            .status: 2=直播中, 0=未播(旧语义保留)
            .title / .owner.nickname / .user_count_str
        - data.user.nickname: 主播昵称
        """
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "errcode": -3,
                "errmsg": "non-dict payload",
                "state": classify_error("douyin", -3, "non-dict").value,
            }
        sc = payload.get("status_code", -1)
        data = payload.get("data") or {}
        if sc != 0:
            # 错误信息优先取 prompts(抖音惯例),fallback 到 message
            msg = data.get("prompts") or data.get("message") or payload.get("message") or "unknown"
            return {
                "ok": False,
                "errcode": sc,
                "errmsg": msg,
                "state": classify_error("douyin", sc, msg).value,
            }

        # 房间详情:新结构 data.data[0],兼容旧结构 data.room
        inner = None
        if isinstance(data.get("data"), list) and data["data"]:
            inner = data["data"][0]
        room = data.get("room") or inner or {}
        status = room.get("status", 0)
        try:
            status = int(status)
        except (ValueError, TypeError):
            status = -1

        owner = room.get("owner") or {}
        # 2026-08-14: 真实开播时间(enter API data.data[0].start_time, unix 秒; 0=未知)
        try:
            live_started_at = int(room.get("start_time") or 0) or None
        except (ValueError, TypeError):
            live_started_at = None
        return {
            "ok": True,
            "room_id": str(data.get("enter_room_id") or room.get("id_str") or room.get("id", "")),
            "web_rid": str(room.get("web_rid") or ""),
            "status": status,
            "status_str": str(room.get("status_str") or LIVE_STATUS_MAP.get(status, f"unknown({status})")),
            "title": room.get("title", ""),
            "nickname": owner.get("nickname") or data.get("user", {}).get("nickname", ""),
            "user_count": str(room.get("user_count_str") or room.get("user_count") or ""),
            "live_started_at": live_started_at,
            "state": classify_platform_status("douyin", status).value,
        }

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
                "state": classify_error("douyin", -4, str(e)).value,
            }

        if parsed["needs_redirect"]:
            expanded = self._expand_short_url(url)
            if not expanded:
                return {
                    "ok": False,
                    "errcode": -5,
                    "errmsg": "short url expand failed",
                    "raw": url,
                    "state": classify_error("douyin", -5, "short url expand failed").value,
                }
            room_id = self._extract_room_id_from_url(expanded)
            if not room_id:
                return {
                    "ok": False,
                    "errcode": -6,
                    "errmsg": "no room_id in expanded url",
                    "raw": url,
                    "expanded": expanded,
                    "state": classify_error("douyin", -6, "no room_id in expanded url").value,
                }
        else:
            room_id = parsed["room_id"]

        # user 主页: stable sec_uid → first use the formal StreamGet gateway.
        # The browser-signed profile API remains a secondary source because its
        # signature script is not guaranteed to initialize in a headless worker.
        if room_id is None and parsed.get("is_user_page"):
            sec_uid = parsed.get("user_id")
            try:
                pr = self._probe_profile_via_streamget(sec_uid)
                if pr.get("ok"):
                    return {
                        "ok": True,
                        "room_id": pr.get("room_id"),
                        "nickname": pr.get("nickname"),
                        "title": pr.get("title"),
                        "raw_status": pr.get("raw_status"),
                        "source": pr.get("source"),
                        "raw": url,
                        "user_id": sec_uid,
                        "state": pr["state"],
                    }
                streamget_error = (
                    f"unrecognized explicit status={pr.get('raw_status')!r}"
                )
            except Exception as e:
                streamget_error = str(e)[:60]

            try:
                from api.services.douyin_session import probe_user_live_status
                pr = probe_user_live_status(sec_uid)
                if pr.get("ok"):
                    return {
                        "ok": True,
                        "room_id": pr.get("room_id"),
                        "live_status": pr.get("live_status"),
                        "nickname": pr.get("nickname"),
                        "follower_count": pr.get("followers"),
                        "source": "douyin_logged_in_profile",
                        "raw": url,
                        "user_id": sec_uid,
                        "state": pr["state"],
                    }
                session_error = pr.get("error") or "登录态探测失败"
            except Exception as e:
                session_error = f"登录态探测异常: {str(e)[:60]}"
            return {
                "ok": False,
                "errcode": -8,
                "errmsg": f"主页探测失败: StreamGet={streamget_error}; session={session_error}",
                "raw": url,
                "user_id": sec_uid,
                "state": LiveStatus.UNKNOWN.value,
            }

        payload = self._fetch_status(room_id)
        result = self._parse_status_payload(payload)
        if not result.get("ok"):
            result["raw"] = url
        return result

    def is_live(self, url: str) -> bool:
        s = self.get_status(url)
        return s.get("state") == LiveStatus.ONLINE.value


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python adapter.py <douyin_url_or_roomid>")
        print("Example: python adapter.py https://live.douyin.com/7234567890123456789")
        sys.exit(1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    a = DouyinAdapter()
    out = a.get_status(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
