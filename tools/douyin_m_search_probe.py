"""试移动搜索专用端点: m.search.douyin.com — 老接口反爬可能弱。"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

KEYWORD = "大斌子"
PROBES_DIR = Path(__file__).parent / "_probes"

UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

# 候选 URLs
URLS = [
    f"https://m.search.douyin.com/suggest/?keyword={KEYWORD}",
    f"https://www.douyin.com/aweme/v1/web/search/item/?keyword={KEYWORD}&offset=0&count=10&search_id=&pc_client_type=1&version_code=190500&version_name=19.5.0&cookie_enabled=true&platform=PC&aid=6383",
    f"https://www.douyin.com/aweme/v1/web/search/user/?keyword={KEYWORD}&offset=0&count=10&search_id=&pc_client_type=1&version_code=190500&version_name=19.5.0&cookie_enabled=true&platform=PC&aid=6383",
]


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ])
    ctx = browser.new_context(
        user_agent=UA_MOBILE,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
    )
    page = ctx.new_page()

    # 1. 直接看 m.search.douyin.com 的 HTML 结构 (这是移动搜索页面)
    url = "https://m.search.douyin.com/"
    print(f"\n=== {url} ===")
    t0 = time.perf_counter()
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  goto err: {e}")

    html = page.content()
    print(f"  HTML: {len(html)} chars")
    print(f"  follower_count: {len(re.findall(r'\"follower_count\"\\s*:\\s*\\d+', html))}")
    print(f"  nickname: {len(re.findall(r'\"nickname\"', html))}")
    print(f"  sec_uid: {len(re.findall(r'\"sec_uid\"', html))}")
    (PROBES_DIR / "douyin_m_search.html").write_text(html, encoding="utf-8")

    # 2. 用 page.evaluate fetch 一个内部 endpoint
    print(f"\n=== 内部 fetch 测试 ===")
    test_urls = [
        f"https://www.douyin.com/aweme/v1/web/search/item/?keyword={KEYWORD}&count=5",
        f"https://www.douyin.com/aweme/v1/web/search/user/?keyword={KEYWORD}&count=5",
    ]
    for tu in test_urls:
        try:
            r = page.evaluate("""async (u) => {
                try {
                    const res = await fetch(u, {credentials: 'include'});
                    const txt = await res.text();
                    return {status: res.status, len: txt.length, preview: txt.slice(0, 800)};
                } catch (e) {
                    return {error: String(e).slice(0, 100)};
                }
            }""", tu)
            print(f"\n  [{r.get('status', 'ERR')}] {tu}")
            print(f"    {str(r)[:500]}")
        except Exception as e:
            print(f"  eval err: {e}")

    ctx.close()
    browser.close()