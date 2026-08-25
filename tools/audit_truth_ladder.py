"""P0 Core Correctness Audit — 五列对照: 平台真实 / Adapter / DB / API / UI。

对真实订阅的主播逐一对照, 定位直播状态责任层。
用法: .venv/Scripts/python.exe tools/audit_truth_ladder.py
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 订阅主播列表(pa_id, platform, name, url)
SUBS = [
    (86, "huya", "Zz1tai姿态", "https://www.huya.com/333003"),
    (87, "douyin", "旭旭宝宝", "https://www.douyin.com/user/MS4wLjABAAAAXcusadpsns9kBnsCcbvD8-Xuv2pFqH4X2rs-P2fnw7U"),
    (88, "douyin", "陈伯(全能王)", "https://www.douyin.com/user/MS4wLjABAAAAe6cnO6wkp9c-onOKNWD2sv-x4e61H4HHbRqNWgyZUD0"),
    (89, "douyin", "阿哲", "https://www.douyin.com/user/MS4wLjABAAAAD45-u7wA2lXFIJQEdtCaO-PoJynkqEHKHUGQx4dmesc"),
]


# ── 第 1 列: 平台真实状态(独立于本项目代码, 直接访问平台) ──
def platform_truth_huya(url: str) -> dict:
    """虎牙: 桌面版 body.liveStatus-on class + 移动版 eLiveStatus 双确认。"""
    import httpx
    UA_DESK = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
    UA_MOB = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
    rid = url.rstrip("/").split("/")[-1]
    result = {"method": "multi", "states": []}
    try:
        r = httpx.get(f"https://www.huya.com/{rid}", headers={"User-Agent": UA_DESK}, timeout=10, follow_redirects=True)
        desktop = r.text
        on = 'class="liveStatus-on' in desktop or 'liveStatus-on' in desktop[:60000]
        off = 'class="liveStatus-off' in desktop
        result["states"].append(f"desktop:{'ON' if on else ('OFF' if off else '?')}")
    except Exception as e:
        result["states"].append(f"desktop:ERR({str(e)[:20]})")
    try:
        r2 = httpx.get(f"https://m.huya.com/{rid}", headers={"User-Agent": UA_MOB}, timeout=10, allow_redirects=True)
        mob = r2.text
        m = re.search(r'"eLiveStatus"\s*:\s*(\d+)', mob)
        result["states"].append(f"mobile:eLiveStatus={m.group(1) if m else '?'}")
    except Exception as e:
        result["states"].append(f"mobile:ERR({str(e)[:20]})")
    result["verdict"] = "ONLINE" if any("ON" in s for s in result["states"]) else (
        "OFFLINE" if any("OFF" in s for s in result["states"]) else "UNKNOWN")
    return result


def platform_truth_douyin(url: str) -> dict:
    """抖音 user 主页: 无登录态只能拿 title(昵称), 状态无法独立确认。"""
    import httpx
    result = {"method": "unauth_limited", "states": []}
    try:
        r = httpx.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
            "Accept": "text/html",
        }, timeout=10, follow_redirects=True)
        html = r.text
        m = re.search(r"<title[^>]*>([^<]*)</title>", html)
        result["states"].append(f"title={m.group(1) if m else '?'}")
        result["verdict"] = "NEEDS_LOGIN"  # 状态需登录态, 无法匿名确认
    except Exception as e:
        result["states"].append(f"ERR({str(e)[:30]})")
        result["verdict"] = "UNKNOWN"
    return result


# ── 第 2 列: Adapter 直探 ──
def adapter_probe(platform: str, url: str) -> dict:
    try:
        from platform_adapters.huya.adapter import HuyaAdapter
        from platform_adapters.douyin.adapter import DouyinAdapter
        cls = {"huya": HuyaAdapter, "douyin": DouyinAdapter}[platform]
        r = cls().get_status(url)
        return {
            "state": r.get("state"),
            "ok": r.get("ok"),
            "raw": {k: v for k, v in r.items() if k not in ("state", "ok", "raw")},
        }
    except Exception as e:
        return {"state": "EXCEPTION", "ok": False, "err": str(e)[:60]}


async def db_state(pa_id: int) -> dict:
    from sqlalchemy import text
    from core.db import engine
    async with engine.connect() as conn:
        pa = (await conn.execute(text(
            "SELECT last_status, last_checked_at FROM platform_accounts WHERE id=:i"), {"i": pa_id})).fetchone()
        sess = (await conn.execute(text(
            "SELECT id, state, started_at, ended_at FROM live_sessions "
            "WHERE platform_account_id=:i AND ended_at IS NULL"), {"i": pa_id})).fetchall()
        return {
            "pa": {"last_status": pa[0], "last_checked_at": str(pa[1]) if pa[1] else None} if pa else None,
            "open_sessions": [{"id": s[0], "state": s[1], "started_at": str(s[2])} for s in sess],
        }


async def api_state() -> dict:
    """第 4 列: 首页/订阅 API 返回。"""
    import httpx
    base = "http://127.0.0.1:8899/api/v1"
    subs = httpx.get(f"{base}/subscriptions?openid=dev_miniapp_local_001", timeout=8).json()
    active = httpx.get(f"{base}/lives/active?openid=dev_miniapp_local_001", timeout=8).json()
    sub_map = {s["platform"] + ":" + str(s.get("platform_user_id", "")): s for s in subs}
    active_names = {i["anchor_name"] for i in active.get("items", [])}
    return {
        "subs": [{"name": s.get("display_name"), "platform": s.get("platform"),
                  "is_live": s.get("is_live"), "last_status": s.get("last_status")} for s in subs],
        "active_names": sorted(active_names),
    }


async def main() -> None:
    print("=" * 100)
    print("P0 Core Correctness Audit — 直播状态五列对照")
    print("=" * 100)

    api = await api_state()
    api_sub_map = {s["name"]: s for s in api["subs"]}

    for pa_id, platform, name, url in SUBS:
        print(f"\n{'─'*100}")
        print(f"▶ {name} [{platform}] pa={pa_id}")
        print(f"{'─'*100}")

        # 列 1: 平台真实状态
        t0 = time.perf_counter()
        truth = platform_truth_huya(url) if platform == "huya" else platform_truth_douyin(url)
        print(f"  ① 平台真实 : {truth['verdict']:<15} ({', '.join(truth['states'])}) [{int((time.perf_counter()-t0)*1000)}ms]")

        # 列 2: Adapter 直探
        t0 = time.perf_counter()
        ad = adapter_probe(platform, url)
        print(f"  ② Adapter  : state={ad['state']:<12} ok={ad['ok']} [{int((time.perf_counter()-t0)*1000)}ms] {json.dumps(ad['raw'], ensure_ascii=False)[:100]}")

        # 列 3: DB
        db = await db_state(pa_id)
        print(f"  ③ DB       : last_status={db['pa']['last_status'] if db['pa'] else 'N/A':<12} "
              f"checked={db['pa']['last_checked_at'] if db['pa'] else 'N/A'}")
        if db["open_sessions"]:
            for s in db["open_sessions"]:
                print(f"                open_session id={s['id']} state={s['state']} started={s['started_at']}")

        # 列 4: API
        api_item = api_sub_map.get(name)
        if api_item:
            print(f"  ④ API      : subscriptions.is_live={api_item['is_live']} last_status={api_item['last_status']}")
        print(f"                lives/active 包含: {'是' if name in api['active_names'] else '否'}")

        # 列 5: UI(前端读的字段 — 从代码确认)
        print(f"  ⑤ UI       : 首页读 lives/active(OPEN session); 订阅页读 subscriptions.is_live(DB last_status)")

        # 责任层判定
        print(f"\n  责任层判定:")
        t = truth["verdict"]
        a = ad["state"]
        d = db["pa"]["last_status"] if db["pa"] else None
        live_open = bool(db["open_sessions"])
        if platform == "huya":
            if t == "ONLINE" and a == "ONLINE" and d == "ONLINE":
                print(f"    一致 ✅ 平台=Adapter=DB=ONLINE, 显示直播中正确")
            elif t == "ONLINE" and d != "ONLINE":
                print(f"    ⚠️ 平台 ONLINE 但 DB={d} → Worker/状态机层问题(探测未更新或状态机未转换)")
            elif t == "OFFLINE" and d == "ONLINE":
                print(f"    ⚠️ 平台 OFFLINE 但 DB=ONLINE → Worker/状态机层问题(下播未被确认)")
            elif t == "OFFLINE" and d == "OFFLINE" and live_open:
                print(f"    ⚠️ 平台/DB 均 OFFLINE 但仍有 OPEN session → LiveSessionEngine 未关闭 session")
            elif t == "OFFLINE" and d == "OFFLINE" and not live_open:
                print(f"    一致 ✅ 平台=DB=OFFLINE")
            else:
                print(f"    ? 平台={t} Adapter={a} DB={d} — 需人工判断")
        else:
            print(f"    (抖音需登录态, 状态真实性验证依赖 P0-S1 登录态探测)")

    print(f"\n{'='*100}")
    print("Audit 完成")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
