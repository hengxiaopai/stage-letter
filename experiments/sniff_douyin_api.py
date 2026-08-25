"""嗅探 live.douyin.com 的网络请求,找包含真实 room_id/web_rid 的 API 响应。
输出:每个匹配请求的 URL + 响应里的数字字段样例。
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parents[1] / "experiments" / "data"

WATCH_KW = ("webcast", "room", "feed", "recommend", "list", "douyin.com/api")


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=(OUT_DIR / "pw_douyin_profile").as_posix(),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_response(resp):
            url = resp.url
            if not any(k in url.lower() for k in WATCH_KW):
                return
            try:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct and "javascript" not in ct:
                    return
                body = resp.text()
                # 只打印有 19 位数字或 room 关键字的
                if re.search(r'\d{19}', body) or 'room' in url.lower():
                    print(f"\n### {resp.status} {url[:140]}")
                    # 提取 body 中 19 位数字上下文
                    for m in list(re.finditer(r'"(\w+)":\s*"?(\d{19})"?', body))[:5]:
                        print(f"   {m.group(1)} = {m.group(2)}")
                    # 打印 body 前 300 字符
                    print("   BODY[:300]:", body[:300].replace(chr(10), ' '))
            except Exception as e:
                print("ERR on", url[:80], str(e)[:60])

        page.on("response", on_response)
        print("打开 live.douyin.com ...")
        page.goto("https://live.douyin.com/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(8000)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(5000)
        print("\n=== 嗅探完成 ===")
        ctx.close()


if __name__ == "__main__":
    main()
