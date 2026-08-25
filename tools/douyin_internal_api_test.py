"""最后测试: 站在 www.douyin.com 主页上, 用 fetch() 调内部 search/user endpoint。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

KEYWORD = "大斌子"

UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ])
    ctx = browser.new_context(
        user_agent=UA_PC,
        viewport={"width": 1440, "height": 900},
    )
    page = ctx.new_page()

    # 先打开 www.douyin.com (让它注入 cookie)
    print("加载 www.douyin.com 主页...")
    try:
        page.goto("https://www.douyin.com/", timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
    except Exception as e:
        print(f"  主页加载 err: {e}")

    print(f"  cookies: {ctx.cookies()[:3]}")

    # 通过 page.evaluate 调内部 endpoint
    endpoints = [
        # 抖音通用 search API
        ("search/item/", f"https://www.douyin.com/aweme/v1/web/search/item/?keyword={KEYWORD}&count=5&offset=0&search_source=normal_search&pc_client_type=1&aid=6383"),
        # search/user 专用
        ("search/user/", f"https://www.douyin.com/aweme/v1/web/search/user/?keyword={KEYWORD}&count=5&offset=0&search_source=normal_search&pc_client_type=1&aid=6383"),
        # search/item 用 type=user
        ("search/item?type=user", f"https://www.douyin.com/aweme/v1/web/search/item/?keyword={KEYWORD}&count=5&offset=0&search_source=normal_search&pc_client_type=1&aid=6383&type=user"),
        # general 端点
        ("general/search/single/", f"https://www.douyin.com/aweme/v1/web/general/search/single/?keyword={KEYWORD}&count=5&offset=0&pc_client_type=1&aid=6383"),
    ]

    print(f"\n=== 测试内部 endpoint (跨域 / fetch 直接调) ===")
    for name, url in endpoints:
        try:
            r = page.evaluate("""async (u) => {
                try {
                    const res = await fetch(u, {
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                        }
                    });
                    const txt = await res.text();
                    return {status: res.status, ctype: res.headers.get('content-type'), len: txt.length, preview: txt.slice(0, 1500)};
                } catch (e) {
                    return {error: String(e).slice(0, 200)};
                }
            }""", url)
            status = r.get('status', r.get('error', 'ERR'))
            print(f"\n--- {name} [{status}] ---")
            print(f"  {r.get('preview', str(r))[:1000]}")
        except Exception as e:
            print(f"  eval err: {e}")

    ctx.close()
    browser.close()