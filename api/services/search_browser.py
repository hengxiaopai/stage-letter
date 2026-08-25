"""Playwright 浏览器搜索 + 结构化结果。

V2 (2026-08-13) 改造:
- 每个 search_* 函数返回 SearchResult {status, items, hint, ms_used, source}
- status enum: SUCCESS / EMPTY / DEGRADED / TIMEOUT / BLOCKED / PARSE_ERROR
- 8s 硬超时(可覆盖)
- 抖音解析策略明确: 登录态强制 → status=BLOCKED, hint="需登录，建议粘贴链接"
- 新增 parse_douyin_user_page(url) 走粘贴链接路径

P0-09 根因:
  - 抖音 H5/PC 搜索的 user 数据需要登录态,无登录直接 2483
  - HTML 仅含 aweme_info.author(视频作者),无完整 user 列表,无 follower_count
  - 因此 douyin 走 playwright 搜索永远 False Negative (除非登录)
  - UI 必须明示「粘贴链接」作为最可靠路径
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("stageletter.search.browser")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"

DEFAULT_TIMEOUT_S = 8

# 统一单调时钟(不能 time.time()/perf_counter() 混用)
_clock = time.perf_counter


# ─────────────────────────────────────────────────────────────────────
# 结构化返回
# ─────────────────────────────────────────────────────────────────────

class Status:
    SUCCESS = "SUCCESS"           # 拿到正常结果(items 可能 0 个,但流程成功)
    EMPTY = "EMPTY"               # 流程成功,真的没结果
    DEGRADED = "DEGRADED"         # 部分成功(降级,走了 DOM 兜底)
    TIMEOUT = "TIMEOUT"           # 超时
    BLOCKED = "BLOCKED"           # 被风控/需登录
    PARSE_ERROR = "PARSE_ERROR"   # 解析失败


@dataclass
class SearchResult:
    status: str
    items: list[dict]
    ms_used: int = 0
    hint: str = ""            # 给前端的提示
    source: str = ""          # 哪条路径产出: aweme_dom / loadmore_api / user_page / local_index
    platform: str = ""
    keyword: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _ok(items: list[dict], ms: int, source: str, hint: str = "", platform: str = "", keyword: str = "") -> SearchResult:
    """正常返回。items 长度 0 表示 EMPTY,>0 表示 SUCCESS。"""
    status = Status.SUCCESS if items else Status.EMPTY
    return SearchResult(
        status=status,
        items=items,
        ms_used=ms,
        source=source,
        hint=hint,
        platform=platform,
        keyword=keyword,
    )


def _err(status: str, ms: int, hint: str, platform: str = "", keyword: str = "", source: str = "") -> SearchResult:
    return SearchResult(
        status=status,
        items=[],
        ms_used=ms,
        source=source,
        hint=hint,
        platform=platform,
        keyword=keyword,
    )


# ─────────────────────────────────────────────────────────────────────
# 内部: 带超时的 playwright 启动 (timeout 共享 budget)
# ─────────────────────────────────────────────────────────────────────

def _launch():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ])
    return p, browser


class _HardTimeout(Exception):
    pass


def _watchdog(deadline_epoch: float, label: str):
    """子线程 watchdog, deadline 到了 raise。"""
    def _run():
        remaining = deadline_epoch - _clock()
        if remaining > 0:
            time.sleep(remaining)
        # 到点了 raise 进主线程(主线程通过定期 _clock() 检查)
        # 实际上 playwright 同步 API 不能被外部 raise, 所以这里只用作日志
        logger.warning(f"[{label}] watchdog fired")
    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────────────────
# 虎牙
# ─────────────────────────────────────────────────────────────────────

def _parse_huya_item(a) -> dict | None:
    """解析虎牙主播 tab 搜索结果项(2026-08-13 重写)。

    卡片结构(实测):
      <a href="https://www.huya.com/video/u/{uid}" title="房间号：10151177" class="new-clickstat">
        <div class="avatar"><img src=... alt="JQK丶阿哲"></div>
        <div class="nick">JQK丶<em class="type-keyword">阿哲</em></div>
        <div class="room">粉丝数: 5.6万</div>
      </a>

    - 房间号: title 属性 "房间号：数字"(优先); 兜底 href huya.com/数字
    - 昵称: .nick 文本(inner_text 含 em 内容)
    - 粉丝数: .room "粉丝数: X万"
    """
    try:
        href = a.get_attribute("href") or ""
        # 房间号: title 属性优先(主播tab卡片 href 是 video/u/{uid}, 无房间号)
        rid = ""
        title_attr = a.get_attribute("title") or ""
        m = re.search(r"房间号[：:]\s*(\d+)", title_attr)
        if m:
            rid = m.group(1)
        else:
            m = re.search(r"huya\.com/(\d{4,})", href)
            if m:
                rid = m.group(1)
        if not rid:
            return None

        # 昵称: .nick 或 img alt
        display_name = ""
        nick_el = a.query_selector(".nick")
        if nick_el:
            display_name = (nick_el.inner_text() or "").strip()
        if not display_name:
            img_el = a.query_selector("img")
            display_name = (img_el.get_attribute("alt") or "") if img_el else ""

        # 粉丝数: .room "粉丝数: 5.6万"
        fans = 0
        room_el = a.query_selector(".room")
        if room_el:
            room_txt = (room_el.inner_text() or "").strip()
            fans_str = re.sub(r"房间号.*$", "", room_txt)
            if "万" in fans_str:
                num = re.sub(r"[^\d.]", "", fans_str)
                fans = int(float(num) * 10000) if num else 0
            else:
                fans_raw = re.sub(r"\D", "", fans_str)
                fans = int(fans_raw) if fans_raw else 0

        avatar_el = a.query_selector("img")
        avatar = avatar_el.get_attribute("src") if avatar_el else None
        return {
            "platform": "huya",
            "user_id": rid,
            "display_name": display_name,
            "avatar": avatar,
            "fans": fans,
            "canonical_url": f"https://www.huya.com/{rid}",
            "is_live": True,
        }
    except Exception:
        return None


def search_huya(keyword: str, limit: int = 10, timeout_s: float = DEFAULT_TIMEOUT_S) -> SearchResult:
    """虎牙主播搜索(主播 tab 昵称匹配) + 相关性过滤。

    2026-08-13 修正(用户反馈): ?sk= 直达返回的是「直播」tab(房间标题匹配),
    会出现"英雄联盟赛事/斯诺克"等与主播名无关的推荐。
    正确做法: 切「主播」tab(昵称匹配) + 输入关键词 + 回车 + 相关性过滤。

    相关性过滤: display_name 必须与 keyword 有重合
      (kw in name 或 name in kw), 过滤无关推荐。
    """
    t0 = time.perf_counter()
    platform = "huya"
    p, browser = _launch()
    try:
        deadline = t0 + timeout_s
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        def _relevant(name: str) -> bool:
            """主播名与关键词相关性判断(去空格/大小写后互相包含)。"""
            a = name.replace(" ", "").lower()
            b = keyword.replace(" ", "").lower()
            return (b in a) or (a in b)

        # ── 主流程: 打开搜索页 → 点「主播」tab → 输入 + 回车 ──
        page.goto(
            "https://www.huya.com/search",
            timeout=min(4000, int(remaining_ms(deadline))),
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(min(2200, max(1200, int(remaining_ms(deadline) - 1500))))

        if _clock() >= deadline:
            return _err(Status.TIMEOUT, int((_clock()-t0)*1000),
                        "虎牙搜索初始化超时", platform, keyword, source="huya_dom")

        try:
            page.evaluate("""
                () => {
                  const els = document.querySelectorAll('span.clickstat, div.clickstat, a.clickstat');
                  for (const el of els) {
                    if ((el.innerText || '').trim() === '主播') { el.click(); return true; }
                  }
                  return false;
                }
            """)
            page.wait_for_timeout(min(1000, int(remaining_ms(deadline) - 200)))
        except Exception:
            pass

        if _clock() >= deadline:
            return _err(Status.TIMEOUT, int((_clock()-t0)*1000),
                        "虎牙搜索超时", platform, keyword, source="huya_dom")

        # 输入关键词 + 回车(选可见的 input)
        box = None
        for candidate in page.query_selector_all("input[type='text']"):
            r = candidate.bounding_box()
            if r and r["width"] > 50 and r["height"] > 20:
                box = candidate
                break
        if box:
            box.click()
            box.fill(keyword)
            box.press("Enter")
        else:
            page.goto(f"https://www.huya.com/search?sk={keyword}",
                      timeout=int(remaining_ms(deadline)), wait_until="domcontentloaded")

        # 等结果(轮询: 结果出现即返回, 不超过 deadline; 避免固定等待拖慢)
        out = []
        # poll 截止 = min(deadline 总上限, 当前 + 5s); 修复 goto 耗时未计入导致的超 10s
        poll_deadline = min(deadline, _clock() + 5.0)
        while _clock() < poll_deadline:
            cards = page.query_selector_all("a.new-clickstat")
            found = []
            for a in cards:
                item = _parse_huya_item(a)
                # 相关性过滤: 与关键词无关的推荐(赛事/频道)直接丢弃
                if item and item["display_name"] and _relevant(item["display_name"]):
                    found.append(item)
                if len(found) >= limit:
                    break
            if found:
                out = found
                break
            page.wait_for_timeout(600)

        # 最后一次尝试(接近 deadline)
        if not out and _clock() < deadline:
            cards = page.query_selector_all("a.new-clickstat")
            for a in cards:
                item = _parse_huya_item(a)
                if item and item["display_name"] and _relevant(item["display_name"]):
                    out.append(item)
                if len(out) >= limit:
                    break

        ctx.close()
        ms = int((_clock()-t0)*1000)
        return _ok(out, ms, source="huya_dom", platform=platform, keyword=keyword)
    except Exception as e:
        ms = int((_clock()-t0)*1000)
        logger.warning(f"[huya] 搜索异常: {e}")
        return _err(Status.PARSE_ERROR if "selector" in str(e).lower() else Status.TIMEOUT,
                    ms, f"虎牙搜索异常: {str(e)[:50]}", platform, keyword)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


def remaining_ms(deadline_epoch: float) -> int:
    return max(500, int((deadline_epoch - _clock()) * 1000))


# ─────────────────────────────────────────────────────────────────────
# 抖音 — V2: 不再做搜索(必 False Negative),直接返回 BLOCKED + 提示粘贴
# ─────────────────────────────────────────────────────────────────────

DOUYIN_BLOCKED_HINT = "抖音需登录才能搜主播。手机抖音App打开主播主页 → 分享 → 复制链接 → 粘贴到下方,无需电脑"


def search_douyin(keyword: str, limit: int = 10, timeout_s: float = DEFAULT_TIMEOUT_S) -> SearchResult:
    """抖音按昵称搜索 — 已知 False Negative(需登录态),直接返回 BLOCKED 引导粘贴链接。

    保留函数是为了不破坏调用链,但内部不再做实际搜索。
    真实可用路径见 parse_douyin_user_page(url) — 粘贴链接走 user page 解析。

    P0-09 根因报告:
      - aweme/v1/web/search/item/ → status_code 2483 "请先登录"
      - aweme/v1/web/search/user/ → 404 Unsupported path (Janus, 已废弃)
      - H5 HTML 仅含 aweme_info.author (视频作者), 无完整 user 列表, 无 follower_count
      - PC Web 是 RSC 流式 SSR, HTML 完全没有 user 字段, 21 个 XHR 全是配置类
    """
    return _err(
        status=Status.BLOCKED,
        ms=0,
        hint=DOUYIN_BLOCKED_HINT,
        platform="douyin",
        keyword=keyword,
        source="login_required",
    )


def search_douyin_logged_in(
    keyword: str, limit: int = 10, timeout_s: float = DEFAULT_TIMEOUT_S
) -> SearchResult:
    """P0-S1: 登录态抖音按昵称搜索(页面内签名 API)。

    前置: 管理员已扫码登录(专用持久化 profile, tools/douyin_login_cli.py login)。
    - 未登录 → AUTH_REQUIRED(BLOCKED + hint 引导管理员扫码)
    - 已登录 → 页面上下文内用抖音自己的 frontierSign 签名调 general/search/single
             → 提取 type=4 user_list 用户卡片(昵称/粉丝/头像/uid)
    - 触发风控 → RATE_LIMITED/BLOCKED(诚实上报, 不自动绕)

    2026-08-14 实测: 搜"大斌子"返回「大斌子（传媒副总版）」✅
    """
    from api.services.douyin_session import PROFILE_DIR, ensure_valid, mark_invalid
    from playwright.sync_api import sync_playwright

    t0 = time.perf_counter()
    platform = "douyin"

    # 1. 登录态校验(5 分钟缓存; 失效 → AUTH_REQUIRED)
    auth = ensure_valid()
    if not auth.get("ok"):
        return _err(
            status=Status.BLOCKED,
            ms=int((_clock()-t0)*1000),
            hint="抖音搜索需登录态: 请管理员运行 tools/douyin_login_cli.py login 扫码后重试",
            platform=platform,
            keyword=keyword,
            source="auth_required",
        )

    # 2. 页面内签名搜索
    p = None
    try:
        p = sync_playwright().start()
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        # 浏览器启动和持久化 profile 恢复不应消耗页面签名器的整个等待预算。
        # 否则冷启动后只剩数秒，已登录用户会被错误报成搜索超时。
        deadline = _clock() + timeout_s
        page = ctx.new_page()
        # 抖音首页的 DOMContentLoaded 在网络抖动时会延后；此前把剩余预算
        # 压到 3~4 秒并等待 domcontentloaded，导致“已登录”也直接超时。
        # 搜索只需要页面上下文和签名器，先在 commit 后继续，再显式等签名器。
        page.goto("https://www.douyin.com", timeout=8000, wait_until="commit")
        page.wait_for_function(
            "() => Boolean(window.byted_acrawler && window.byted_acrawler.frontierSign)",
            timeout=min(6000, max(1000, int(remaining_ms(deadline)))),
        )

        users = page.evaluate(
            """async (kw) => {
                const params = new URLSearchParams({
                    keyword: kw,
                    search_source: 'switch_tab',
                    device_platform: 'webapp',
                    aid: '6383',
                    channel: 'channel_pc_web',
                    count: '20',
                });
                const fullUrl = 'https://www.douyin.com/aweme/v1/web/general/search/single/?' + params.toString();
                // P0-LiveTruth: 2483(需登录)偶发 — 重试 2 次, 仍 2483 才判失效
                let data = null;
                for (let attempt = 0; attempt < 3; attempt++) {
                    try { window.byted_acrawler.frontierSign({ url: fullUrl, method: 'GET', body: '', headers: {} }); } catch (e) {}
                    const resp = await fetch(fullUrl, { headers: { 'Accept': 'application/json' } });
                    data = await resp.json();
                    if (data.status_code !== 2483 && !String(data.status_code).includes('login')) break;
                    if (attempt < 2) await new Promise(r => setTimeout(r, 2000));
                }
                if (data.status_code === 2483 || String(data.status_code).includes('login')) {
                    return { error: 'code=' + data.status_code, users: [] };
                }
                const arr = data.data || [];
                const users = [];
                const seen = new Set();
                const pushUser = (ui, src) => {
                    if (!ui || !ui.nickname || !ui.sec_uid) return;
                    if (seen.has(ui.sec_uid)) return;
                    seen.add(ui.sec_uid);
                    const avatar = (ui.avatar_larger && ui.avatar_larger.url_list && ui.avatar_larger.url_list[0])
                                || (ui.avatar_thumb && ui.avatar_thumb.url_list && ui.avatar_thumb.url_list[0])
                                || '';
                    users.push({
                        nickname: ui.nickname,
                        uid: ui.uid,
                        short_id: ui.short_id,
                        sec_uid: ui.sec_uid,
                        followers: ui.follower_count,
                        signature: (ui.signature || '').slice(0, 80),
                        custom_verify: ui.custom_verify,
                        avatar: avatar,
                        source: src,
                    });
                };
                for (const it of arr) {
                    // 用户卡片(type=4)
                    if (it.type === 4) {
                        for (const u of (it.user_list || [])) pushUser(u.user_info || {}, 'user_card');
                    }
                    // 视频作者(type=1) — 2026-08-14 修复: 小众主播无用户卡片, 只有视频作者
                    else if (it.aweme_info && it.aweme_info.author) {
                        pushUser(it.aweme_info.author, 'video_author');
                    }
                }
                return { error: null, users };
            }""",
            keyword,
        )

        ctx.close()
        ms = int((_clock()-t0)*1000)

        if users.get("error"):
            # 重试后仍 2483/登录态问题 → 先 probe 确认再标记(偶发 2483 不误标)
            if "code=2483" in str(users["error"]) or "登录" in str(users["error"]):
                try:
                    from api.services.douyin_session import probe_login
                    pr = probe_login()
                    if not pr.get("logged_in"):
                        mark_invalid(str(users["error"]))
                        return _err(Status.BLOCKED, ms, "抖音登录态已失效,请管理员重新扫码", platform,
                                    keyword, source="auth_required")
                except Exception:
                    pass
            # 登录态有效(偶发 2483) → 友好提示, 不标记失效; 用户重试即可
            return _err(Status.BLOCKED, ms, "抖音搜索暂时繁忙,请稍后再试", platform,
                        keyword, source="douyin_api_retryable")

        items = []
        for u in users.get("users") or []:
            uid = u.get("sec_uid") or u.get("uid") or ""
            if not uid:
                continue
            items.append({
                "platform": "douyin",
                "user_id": uid,
                "display_name": u.get("nickname", ""),
                "avatar": u.get("avatar"),
                "fans": u.get("followers") or 0,
                "canonical_url": f"https://www.douyin.com/user/{uid}",
                "is_live": False,
                "followers_unknown": False,
            })
            if len(items) >= limit:
                break

        if not items:
            return _err(Status.EMPTY, ms, "抖音未找到相关主播", platform, keyword,
                        source="douyin_logged_in")
        return _ok(items, ms, source="douyin_logged_in", platform=platform, keyword=keyword)
    except Exception as e:
        ms = int((_clock()-t0)*1000)
        logger.warning(f"[douyin.login_search] 异常: {e}")
        return _err(Status.TIMEOUT, ms, f"抖音搜索异常: {str(e)[:50]}", platform, keyword,
                    source="douyin_logged_in")
    finally:
        try:
            if p is not None:
                p.stop()
        except Exception:
            pass


def parse_douyin_user_page(url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> SearchResult:
    """粘贴抖音链接 → 解析主播基本信息(打开 user 主页,无需登录)。

    支持 URL 形式:
      - https://www.douyin.com/user/{sec_uid}
      - https://v.douyin.com/{short_id}  (短链,需 redirect 一次)
      - https://www.douyin.com/user/MS4wLjABAAAA...

    返回:
      [{platform: "douyin", user_id: {sec_uid}, display_name, avatar, fans, canonical_url, is_live}]
    注: fans 通常拿不到(需登录), 显式置 0
    """
    t0 = time.perf_counter()
    platform = "douyin"
    p, browser = _launch()
    try:
        url = url.strip()
        # 先归一化短链 (v.douyin.com → 需要解析 redirect)
        if "v.douyin.com" in url:
            try:
                ctx0 = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
                page0 = ctx0.new_page()
                page0.goto(url, timeout=int(timeout_s * 1000), wait_until="domcontentloaded")
                url = page0.url  # 解析后的 canonical URL
                ctx0.close()
            except Exception:
                pass

        sec_uid = None
        m = re.search(r"douyin\.com/user/([A-Za-z0-9_\-]+)", url)
        if m:
            sec_uid = m.group(1)

        if not sec_uid:
            return _err(Status.PARSE_ERROR, int((_clock()-t0)*1000),
                        "无法从链接提取 sec_uid (需 https://www.douyin.com/user/{sec_uid} 形式)",
                        platform, url)

        # 打开 user page (无登录可访问, title 含昵称: "似梦的抖音 - 抖音")
        deadline = t0 + timeout_s
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(f"https://www.douyin.com/user/{sec_uid}",
                  timeout=int(timeout_s * 1000), wait_until="domcontentloaded")
        page.wait_for_timeout(min(4500, max(1500, int(remaining_ms(deadline) - 1000))))  # 渲染

        # 提取昵称: 从 SSR HTML 的 <title> 标签(live document.title 会被 RSC 清空,不可靠)
        # title = "似梦的抖音 - 抖音" → "似梦"
        # 2026-08-13 实测: page.title()/evaluate('document.title') 在 RSC 页面可能返回空,
        # 但 page.content() 里的 <title> 标签始终存在
        display_name = ""
        try:
            html = page.content()
            m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                # 格式1: "XXX的抖音 - 抖音" → XXX
                m2 = re.match(r"(.+?)的抖音(?:\s*-\s*抖音)?", title)
                if m2:
                    display_name = m2.group(1).strip()
                else:
                    # 格式2: "XXX - 抖音"
                    m2 = re.match(r"(.+?)\s*-\s*抖音", title)
                    if m2:
                        display_name = m2.group(1).strip()
        except Exception:
            pass

        # 提取 avatar: SSR HTML 里 avatar_thumb.url_list[0]
        avatar = ""
        try:
            if not html:
                html = page.content()
            am = re.search(r'"avatar_thumb":\{[^}]*"url_list":\["([^"]+)"', html)
            if am:
                avatar = am.group(1)
            if not avatar:
                am = re.search(r'"avatar_larger":\{[^}]*"url_list":\["([^"]+)"', html)
                if am:
                    avatar = am.group(1)
        except Exception:
            pass

        # fans: 抖音 user page HTML 通常 *没有* follower_count (需要登录)
        fans = 0
        is_live = False

        if not display_name or display_name in ("抖音", "抖音-记录美好生活"):
            return _err(Status.PARSE_ERROR, int((_clock()-t0)*1000),
                        "抖音页面未提取到昵称(可能需登录或链接无效)",
                        platform, url, source="user_page")

        item = {
            "platform": "douyin",
            "user_id": sec_uid,
            "display_name": display_name,
            "avatar": avatar,
            "fans": fans,
            "canonical_url": f"https://www.douyin.com/user/{sec_uid}",
            "is_live": is_live,
            "followers_unknown": True,  # 提示前端 fans=0 是 unknown 不是 0
        }

        ctx.close()
        ms = int((_clock()-t0)*1000)
        return _ok([item], ms, source="user_page", platform=platform, keyword=url)
    except Exception as e:
        ms = int((_clock()-t0)*1000)
        logger.warning(f"[douyin.parse] 异常: {e}")
        return _err(Status.TIMEOUT, ms, f"抖音链接解析失败: {str(e)[:50]}", platform, url, source="user_page")
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
# 斗鱼
# ─────────────────────────────────────────────────────────────────────

def search_douyu(keyword: str, limit: int = 10, timeout_s: float = DEFAULT_TIMEOUT_S) -> SearchResult:
    """斗鱼直播搜索: 用 ?kw=query 形式打开,从链接提取房间。8s 硬上限。"""
    t0 = time.perf_counter()
    platform = "douyu"
    p, browser = _launch()
    try:
        deadline = t0 + timeout_s
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        # 2026-08-13 优化: goto 超时 4s(不是 8s), 渲染等待 ≤3.5s, 把总耗压进 8s
        page.goto(
            f"https://www.douyu.com/search?kw={keyword}",
            timeout=min(4000, int(remaining_ms(deadline))),
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(min(3500, max(1000, int(remaining_ms(deadline) - 500))))

        # 2026-08-13 重写: 斗鱼搜索卡片是 CSS Modules 混淆类名的 anchorInfo div
        # (无 data-rid, 链接也不是 douyu.com/数字 形式), 旧 a[href] 提取全漏
        # 正确方式: 从卡片文本提取 "房间号(\d+)" + 主播名 + 关注数
        # 2026-08-13 修正: 无登录时斗鱼返回的是热门推荐(赛事/活动), 加相关性过滤丢弃无关结果
        out = []
        if _clock() < deadline:
            try:
                cards = page.evaluate(
                    """() => {
                        const out = [];
                        const els = document.querySelectorAll('[class*="anchorInfo"], [class*="anchorCard"], [class*="userCard"]');
                        for (const el of els) {
                            const txt = (el.innerText || '').trim();
                            const m = txt.match(/房间号\\s*(\\d+)/);
                            if (!m) continue;
                            const img = el.querySelector('img');
                            // 主播名: 优先 h3/title 元素, 兜底取文本首行
                            let name = '';
                            const nameEl = el.querySelector('h3, [class*="title"]');
                            if (nameEl) name = (nameEl.innerText || '').trim();
                            if (!name) name = (txt.split('\\n')[0] || '').trim();
                            // 关注数: "关注 1781.3万"
                            let fans = 0;
                            const fm = txt.match(/关注\\s*([\\d.]+)万/);
                            if (fm) fans = Math.round(parseFloat(fm[1]) * 10000);
                            out.push({
                                rid: m[1],
                                name: name.slice(0, 40),
                                avatar: img ? (img.getAttribute('src') || '') : '',
                                fans,
                            });
                        }
                        return out;
                    }"""
                )
            except Exception:
                cards = []

            def _relevant(name: str) -> bool:
                a = name.replace(" ", "").lower()
                b = keyword.replace(" ", "").lower()
                return (b in a) or (a in b)

            seen_rid = set()
            for c in (cards or []):
                if not c or not c.get("rid") or c["rid"] in seen_rid:
                    continue
                seen_rid.add(c["rid"])
                name = (c.get("name") or "").strip()
                # 清理混入的按钮文字(关注/已关注/订阅/直播等)
                for w in ("关注", "已关注", "订阅", "已订阅", "直播"):
                    name = name.replace(w, "")
                name = name.strip()
                if not name or len(name) > 30:
                    continue
                # 相关性过滤: 无关热门推荐直接丢弃
                if not _relevant(name):
                    continue
                out.append({
                    "platform": "douyu",
                    "user_id": c["rid"],
                    "display_name": name,
                    "avatar": c.get("avatar"),
                    "fans": c.get("fans") or 0,
                    "canonical_url": f"https://www.douyu.com/{c['rid']}",
                    "is_live": True,
                })
                if len(out) >= limit:
                    break
        ctx.close()
        ms = int((_clock()-t0)*1000)
        return _ok(out, ms, source="douyu_dom", platform=platform, keyword=keyword)
    except Exception as e:
        ms = int((_clock()-t0)*1000)
        logger.warning(f"[douyu] 搜索异常: {e}")
        return _err(Status.PARSE_ERROR, ms, f"斗鱼搜索异常: {str(e)[:50]}", platform, keyword)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass
