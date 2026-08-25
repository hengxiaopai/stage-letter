"""从 live.douyin.com/webcast/feed 响应提取真实 web_rid(id_str),筛选直播中(status=2)。

用法: python extract_douyin_webrids.py
输出: 打印 JSON: {web_rid, status, title, user_count, nickname}
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parents[1] / "experiments" / "data"
FEED_KW = "webcast/feed"


def parse_feed(body: str) -> list:
    """解析 feed 响应,返回 [{web_rid, status, title, nickname, user_count}]"""
    out = []
    try:
        data = json.loads(body)
    except Exception:
        return out
    for item in data.get("data", []):
        d = item.get("data") or {}
        rid = d.get("id_str") or d.get("id")
        if rid and str(rid).isdigit() and len(str(rid)) >= 15:
            out.append({
                "web_rid": str(rid),
                "status": d.get("status"),
                "title": (d.get("title") or "")[:60],
                "nickname": (d.get("owner", {}).get("nickname") or "")[:30],
                "user_count": d.get("user_count"),
            })
    return out


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=(OUT_DIR / "pw_douyin_profile").as_posix(),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        rooms = []

        def on_response(resp):
            if FEED_KW not in resp.url:
                return
            try:
                body = resp.text()
                rooms.extend(parse_feed(body))
            except Exception:
                pass

        page.on("response", on_response)
        page.goto("https://live.douyin.com/", wait_until="domcontentloaded", timeout=30000)
        # 滚动触发多批 feed 加载
        for i in range(8):
            page.wait_for_timeout(1500)
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(800)
        page.wait_for_timeout(3000)
        ctx.close()

    # 去重 + 筛选
    seen = {}
    for r in rooms:
        if r["web_rid"] not in seen:
            seen[r["web_rid"]] = r
    print(f"共捕获 {len(rooms)} 条,去重 {len(seen)} 个房间:")
    for rid, r in sorted(seen.items(), key=lambda kv: -(kv[1].get("user_count") or 0)):
        st = r["status"]
        flag = "  <<< 直播中" if st == 2 else ""
        print(f"  {rid} status={st} users={r['user_count']} | {r['nickname']} | {r['title']}{flag}")

    # 输出直播中(status=2)的
    live = [r for r in seen.values() if r["status"] == 2]
    print(f"\n=== 直播中(status=2): {len(live)} 个 ===")
    for r in live[:15]:
        print(f"  {r['web_rid']}  {r['nickname']}  {r['title'][:40]}  users={r['user_count']}")


if __name__ == "__main__":
    main()
