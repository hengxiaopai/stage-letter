"""P0 Truth Table — 主播直播状态全链路九列排查。

链路: 平台真实 → Adapter 直探 → last_probe_at → DB state → LiveSession
      → Home API → Subscription API → 首页 UI → 订阅 UI

用法: .venv/Scripts/python.exe tools/truth_table.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SUBS = [
    (86, "huya", "Zz1tai姿态", "https://www.huya.com/333003"),
    (87, "douyin", "旭旭宝宝", "https://www.douyin.com/user/MS4wLjABAAAAXcusadpsns9kBnsCcbvD8-Xuv2pFqH4X2rs-P2fnw7U"),
    (88, "douyin", "陈伯(全能王)", "https://www.douyin.com/user/MS4wLjABAAAAe6cnO6wkp9c-onOKNWD2sv-x4e61H4HHbRqNWgyZUD0"),
    (89, "douyin", "阿哲", "https://www.douyin.com/user/MS4wLjABAAAAD45-u7wA2lXFIJQEdtCaO-PoJynkqEHKHUGQx4dmesc"),
]
OPENID = "dev_miniapp_local_001"
BASE = "http://127.0.0.1:8899/api/v1"


# ── 列 1: 平台真实状态(独立直探) ──
def platform_truth(platform: str, url: str) -> str:
    import httpx
    try:
        if platform == "huya":
            rid = url.rstrip("/").split("/")[-1]
            r = httpx.get(f"https://www.huya.com/{rid}", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"},
                timeout=10, follow_redirects=True)
            cls = re.search(r'<body[^>]*class="([^"]*)"', r.text)
            c = cls.group(1) if cls else ""
            return "ONLINE" if "liveStatus-on" in c else ("OFFLINE" if "liveStatus-off" in c else "?")
        return "NEEDS_LOGIN"  # 抖音需登录态
    except Exception as e:
        return f"ERR({str(e)[:20]})"


# ── 列 2: Adapter 直探(抖音=登录态) ──
def adapter_probe(platform: str, url: str) -> str:
    try:
        from platform_adapters.huya.adapter import HuyaAdapter
        from platform_adapters.douyin.adapter import DouyinAdapter
        cls = {"huya": HuyaAdapter, "douyin": DouyinAdapter}[platform]
        r = cls().get_status(url)
        return r.get("state", "?")
    except Exception as e:
        return f"EXC({str(e)[:20]})"


async def main():
    import httpx as hx
    from sqlalchemy import text
    from core.db import engine

    async with engine.connect() as conn:
        rows = {}
        for pa_id, *_ in SUBS:
            pa = (await conn.execute(text(
                "SELECT last_status, last_checked_at, polling_tier FROM platform_accounts WHERE id=:i"),
                {"i": pa_id})).fetchone()
            sess = (await conn.execute(text(
                "SELECT count(*) FROM live_sessions WHERE platform_account_id=:i AND state='OPEN'"),
                {"i": pa_id})).fetchone()
            rows[pa_id] = {"pa": pa, "open_sess": sess[0]}
    await engine.dispose()

    home = hx.get(f"{BASE}/lives/active?openid={OPENID}", timeout=10).json()
    home_names = {i["anchor_name"]: i.get("live_state") for i in home["items"]}
    subs_api = hx.get(f"{BASE}/subscriptions?openid={OPENID}", timeout=10).json()
    sub_map = {s["display_name"]: s for s in subs_api}

    print("=" * 120)
    print("P0 Truth Table — 主播状态全链路对照")
    print("=" * 120)
    print(f"{'主播':<14}{'平台真实':<12}{'Adapter(登录)':<12}{'last_probe_at':<22}{'DB':<14}{'Session':<8}{'HomeAPI':<10}{'SubAPI':<12}{'首页UI':<12}{'订阅UI'}")
    print("-" * 120)

    for pa_id, platform, name, url in SUBS:
        truth = platform_truth(platform, url)
        ad = adapter_probe(platform, url)
        pa = rows[pa_id]["pa"]
        db_state = pa[0] if pa else "N/A"
        last_probe = str(pa[1])[:19] if pa and pa[1] else "never"
        sess = "OPEN" if rows[pa_id]["open_sess"] else "None"

        home_state = home_names.get(name, "—")
        # Home UI 映射(首页分组逻辑)
        home_ui = {"LIVE": "正在直播", "CONFIRMING": "确认中", "UNKNOWN": "未知/失败"}.get(
            home_state, "等待开播" if home_state == "—" else home_state)

        s = sub_map.get(name, {})
        sub_state = s.get("live_state", "?")
        # 订阅 UI 映射(前端旧逻辑: is_live!==true → 未开播)
        sub_ui = "正在直播" if s.get("is_live") is True else (
            "未开播" if s.get("is_live") is False else "未开播(旧逻辑)")
        if sub_state == "UNKNOWN":
            sub_ui = "未开播 ← 疑似错误映射!"

        print(f"{name:<14}{truth:<12}{ad:<12}{last_probe:<22}{db_state:<14}{sess:<8}"
              f"{home_state or '—':<10}{sub_state:<12}{home_ui:<12}{sub_ui}")

    print("-" * 120)
    print("\n⚠ 判断标准:")
    print("  第一个不一致层级 = 状态链断裂点")
    print("  平台真实 != Adapter     → Adapter 层问题")
    print("  Adapter != DB           → Worker/状态机问题")
    print("  DB != Home/Sub API      → API 层问题")
    print("  API state != 页面显示   → 前端映射问题")


if __name__ == "__main__":
    asyncio.run(main())
