"""抖音登录态会话管理 — P0-S1。

架构(用户要求):
- 专用持久化浏览器会话(独立 profile, 不用日常主账号)
- 管理员扫码登录一次 → 登录态复用
- 登录失效 → 标记 AUTH_REQUIRED → 要求管理员重新登录
- 不自动绕验证码或风控(触发风控 → RATE_LIMITED/BLOCKED 诚实上报)

持久化:
- PROFILE_DIR: .workbuddy/douyin_profile (Playwright persistent context 的 cookie/storage)
- STATUS_FILE: .workbuddy/douyin_login.json (登录态元信息: logged_in / username / checked_at / error)

登录态检测:
- 用持久化 cookie 请求抖音搜索 API(未登录返回 2483 "请先登录"; 登录后 code=0)
- 检测失败(网络) → 保持上次状态 + stale 标记
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("stageletter.douyin.session")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = PROJECT_ROOT / ".workbuddy" / "douyin_profile"
STATUS_FILE = PROJECT_ROOT / ".workbuddy" / "douyin_login.json"

# persistent context 同一 profile 不能并发打开(Playwright 锁) — 串行化
import threading
_PROFILE_LOCK = threading.Lock()

# 抖音搜索 API(登录态下可用; 未登录 2483)
SEARCH_ITEM_API = "https://www.douyin.com/aweme/v1/web/search/item/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ─────────────────────────────────────────────────────────────────────
# 登录态元信息(STATUS_FILE)
# ─────────────────────────────────────────────────────────────────────

def _read_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_status(data: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def login_status() -> dict:
    """当前登录态元信息(文件缓存, 不实时探测)。"""
    st = _read_status()
    return {
        "logged_in": bool(st.get("logged_in")),
        "username": st.get("username"),
        "checked_at": st.get("checked_at"),
        "error": st.get("error"),
        "stale": bool(st.get("stale")),
        "profile_dir": str(PROFILE_DIR),
        "status_file": str(STATUS_FILE),
    }


# ─────────────────────────────────────────────────────────────────────
# 登录态探测(用真实 cookie 请求搜索 API)
# ─────────────────────────────────────────────────────────────────────

def probe_login(headless: bool = True, timeout_s: float = 15) -> dict:
    """用持久化 profile 的 cookie 探测搜索 API, 返回真实登录态。

    Returns:
        {"logged_in": bool, "username": str|None, "checked_at": iso,
         "error": str|None, "probe": {code, errmsg}|None}
    """
    from playwright.sync_api import sync_playwright

    t0 = time.time()
    result = {"logged_in": False, "username": None, "checked_at": None, "error": None, "probe": None}

    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        result["error"] = "no_profile(尚未扫码登录)"
        _write_status({**_read_status(), "logged_in": False, "stale": True, "error": result["error"]})
        return result

    try:
        with _PROFILE_LOCK:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                    user_agent=UA,
                )
                try:
                    # 用持久化 cookie 请求搜索 API
                    resp = ctx.request.get(
                        SEARCH_ITEM_API,
                        params={"keyword": "旭旭宝宝", "type": "1", "search_source": "switch_tab"},
                        headers={"Accept": "application/json, text/plain, */*",
                                 "Referer": "https://www.douyin.com/search/"},  # 必须 ASCII(头不允许中文)
                        timeout=timeout_s * 1000,
                    )
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
                    # 登录态判定: status_code==0 → 登录有效(未登录时 2483)
                    # 注意: 登录态下搜索 API 仍需签名参数(params_check), 但这不影响登录态判定
                    code = data.get("code")
                    status_code = data.get("status_code")
                    errmsg = data.get("status_msg") or data.get("errmsg")

                    if code == 0 or status_code == 0:
                        result["logged_in"] = True
                        result["probe"] = {"code": code, "status_code": status_code}
                        # 尝试拿昵称(搜索结果里可能有, 或跳过)
                        result["username"] = "douyin_user"
                        _save_storage_state(ctx)
                    elif code == 2483 or status_code == 2483 or "登录" in str(errmsg or ""):
                        result["logged_in"] = False
                        result["error"] = f"auth_expired(code={code or status_code}: {errmsg})"
                        result["probe"] = {"code": code, "status_code": status_code, "errmsg": errmsg}
                    else:
                        result["logged_in"] = False
                        result["error"] = f"probe_abnormal(code={code or status_code}: {errmsg})"
                        result["probe"] = {"code": code, "status_code": status_code, "errmsg": errmsg}
                finally:
                    ctx.close()
    except Exception as e:
        result["error"] = f"probe_exception: {str(e)[:100]}"
        logger.warning("抖音登录态探测异常: %s", e)

    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    status = _read_status()
    status.update({
        "logged_in": result["logged_in"],
        "username": result["username"] or status.get("username"),
        "checked_at": result["checked_at"],
        "error": result["error"],
        "stale": not result["logged_in"],
    })
    _write_status(status)
    result["checked_ms"] = int((time.time() - t0) * 1000)
    return result


def _save_storage_state(ctx) -> None:
    """把 persistent context 的 cookie/localStorage 导出为 storage_state 文件(搜索用)。"""
    try:
        ss = PROFILE_DIR.parent / "douyin_storage.json"
        ctx.storage_state(path=str(ss))
        logger.info("登录态已导出: %s", ss)
    except Exception as e:
        logger.warning("导出 storage_state 失败: %s", e)


def ensure_valid(timeout_s: float = 15) -> dict:
    """确保登录态有效(探测 + 必要时重试)。登录失效 → AUTH_REQUIRED。"""
    st = login_status()
    # 最近 5 分钟内探测过且 logged_in → 直接信任(避免频繁探测)
    checked_at = st.get("checked_at")
    if st.get("logged_in") and checked_at:
        try:
            last = datetime.fromisoformat(checked_at)
            if (datetime.now(timezone.utc) - last).total_seconds() < 300:
                return {"ok": True, "auth": "VALID", **st}
        except Exception:
            pass
    res = probe_login(headless=True, timeout_s=timeout_s)
    if res.get("logged_in"):
        return {"ok": True, "auth": "VALID", **res}
    return {"ok": False, "auth": "AUTH_REQUIRED", **res}


def mark_invalid(reason: str) -> None:
    """标记登录失效(搜索过程发现 2483/风控时调用)。"""
    st = _read_status()
    st.update({"logged_in": False, "stale": True, "error": reason,
               "checked_at": datetime.now(timezone.utc).isoformat()})
    _write_status(st)
    logger.warning("抖音登录态标记失效: %s", reason)


def run_login(timeout_s: float = 180) -> dict:
    """扫码登录 CLI 核心: headed 打开抖音 → 等用户扫码 → 探测确认 → 保存。

    注意: 需要桌面 GUI(用户可见浏览器), 扫码必须用户手机操作。
    """
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("抖音登录 — 请用手机抖音 App 扫码登录")
    print("(浏览器会自动打开, 扫码完成后等待自动检测)")
    print("=" * 60)

    t0 = time.time()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,  # 必须显示, 用户扫码
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        try:
            page.goto("https://www.douyin.com", timeout=20000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"⚠ 打开抖音首页失败(可能网络): {e}")

        print("\n⌛ 等待扫码登录(最长 180s)...")
        # 轮询探测: 每 5s 检查 cookie 是否出现登录态关键 cookie
        logged = False
        while time.time() - t0 < timeout_s:
            time.sleep(4)
            try:
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                # 登录关键 cookie: sessionid / passport_csrf_token / passport_auth_status
                has_session = bool(cookies.get("sessionid") or cookies.get("sessionid_ss"))
                if has_session:
                    print("✓ 检测到登录 cookie, 正在验证搜索 API 可用性...")
                    # 用当前 context 探测搜索 API
                    res = probe_login_with_context(ctx)
                    if res.get("logged_in"):
                        logged = True
                        break
                    elif "登录" in (res.get("error") or ""):
                        print("⚠ cookie 存在但 API 仍要求登录, 继续等待...")
            except Exception:
                pass

        ctx.close()

    if logged:
        st = _read_status()
        st.update({"logged_in": True, "stale": False, "error": None,
                   "checked_at": datetime.now(timezone.utc).isoformat(),
                   "username": st.get("username") or "douyin_user"})
        _write_status(st)
        print("\n✅ 登录成功! 登录态已持久化:")
        print(f"  profile: {PROFILE_DIR}")
        print(f"  状态文件: {STATUS_FILE}")
        return {"ok": True, **login_status()}

    print("\n❌ 超时未检测到登录(或扫码未完成)")
    return {"ok": False, "error": "timeout"}


def probe_login_with_context(ctx) -> dict:
    """用已打开的 persistent context 探测登录态(扫码流程内用)。"""
    try:
        resp = ctx.request.get(
            SEARCH_ITEM_API,
            params={"keyword": "旭旭宝宝", "type": "1", "search_source": "switch_tab"},
            headers={"Accept": "application/json, text/plain, */*",
                     "Referer": "https://www.douyin.com/search/"},
            timeout=12000,
        )
        data = resp.json()
        code = data.get("code")
        if code == 0:
            return {"logged_in": True, "probe": {"code": code}}
        return {"logged_in": False, "error": f"code={code}"}
    except Exception as e:
        return {"logged_in": False, "error": f"exception: {str(e)[:60]}"}


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="抖音登录态管理(P0-S1)")
    ap.add_argument("cmd", choices=["login", "status", "probe", "logout", "clean"],
                    help="login=扫码登录; status=查看状态; probe=重新探测; logout=登出(清 cookie); clean=清空全部")
    args = ap.parse_args()

    if args.cmd == "login":
        result = run_login()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(json.dumps(login_status(), ensure_ascii=False, indent=2))
    elif args.cmd == "probe":
        print(json.dumps(probe_login(headless=True), ensure_ascii=False, indent=2))
    elif args.cmd == "logout":
        if PROFILE_DIR.exists():
            import shutil
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        st = _read_status()
        st.update({"logged_in": False, "stale": True, "error": "logout"})
        _write_status(st)
        print("已登出(profile 已清除)")
    elif args.cmd == "clean":
        import shutil
        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        if STATUS_FILE.exists():
            STATUS_FILE.unlink(missing_ok=True)
        print("已清空登录态")


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────
# P0-LiveTruth: 登录态 Live Probe(user 主页直播状态)
# ─────────────────────────────────────────────────────────────────────

def probe_user_live_status(sec_uid: str, timeout_s: float = 20) -> dict:
    """P0-LiveTruth: 登录态探测抖音 user 主页直播状态(profile/other API)。

    返回:
        {"ok": True, "live_status": int, "room_id": int, "nickname": str|None,
         "state": "ONLINE"|"OFFLINE", "login": True}
        或 {"ok": False, "error": ..., "auth": "AUTH_REQUIRED"|...}

    枚举(实测): live_status=0 → 未开播(room_id=0); 1 → 直播中(room_id>0)
    """
    from playwright.sync_api import sync_playwright

    t0 = time.time()
    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        return {"ok": False, "error": "no_profile", "auth": "AUTH_REQUIRED"}

    p = None
    try:
        with _PROFILE_LOCK:
            p = sync_playwright().start()
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                user_agent=UA,
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.goto("https://www.douyin.com", timeout=min(10000, int(timeout_s * 1000)),
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            result = page.evaluate(
            """async (sec) => {
                const params = new URLSearchParams({
                    sec_user_id: sec, device_platform: 'webapp', aid: '6383',
                    channel: 'channel_pc_web', publish_video_strategy_type: '2',
                    source: 'channel_pc_web',
                });
                const fullUrl = 'https://www.douyin.com/aweme/v1/web/user/profile/other/?' + params.toString();
                try { window.byted_acrawler.frontierSign({ url: fullUrl, method: 'GET', body: '', headers: {} }); } catch (e) {}
                const resp = await fetch(fullUrl, { headers: { 'Accept': 'application/json' } });
                const data = await resp.json();
                if (data.status_code === 2483 || String(data.status_code).includes('login')) {
                    return { login_required: true };
                }
                const u = data.user || {};
                return { live_status: u.live_status, room_id: u.room_id,
                         nickname: u.nickname, followers: u.follower_count };
            }""",
                sec_uid,
            )
            ctx.close()

            if result.get("login_required"):
                mark_invalid("probe_user_live_status: login required")
                return {"ok": False, "error": "login_required", "auth": "AUTH_REQUIRED",
                        "latency_ms": int((time.time() - t0) * 1000)}

            live_status = result.get("live_status")
            room_id = result.get("room_id")
            state = "ONLINE" if (live_status == 1 and room_id) else (
                "OFFLINE" if live_status == 0 else "UNKNOWN")
            return {
                "ok": True,
                "live_status": live_status,
                "room_id": room_id,
                "nickname": result.get("nickname"),
                "followers": result.get("followers"),
                "state": state,
                "login": True,
                "latency_ms": int((time.time() - t0) * 1000),
            }
    except Exception as e:
        return {"ok": False, "error": f"exception: {str(e)[:80]}",
                "latency_ms": int((time.time() - t0) * 1000)}
    finally:
        try:
            if p is not None:
                p.stop()
        except Exception:
            pass
