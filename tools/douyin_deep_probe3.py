"""深挖 #3: 抓 PC Web 抖音精选搜索页, 长时间等待 hydrate, 记录所有 XHR endpoint。

关键问题:
1. "468.2 万粉丝" 是从哪个 XHR 来的?
2. 用户卡片是不是前端 hydrate 后才出现?
3. PC Web HTML 的 data-id/user_id 字段叫什么?
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

# PC Web 桌面 UA (用户截图是桌面浏览器)
PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

KEYWORD = "大斌子"
URL_PC = f"https://www.douyin.com/jingxuan/search/{KEYWORD}?type=general"

PROBES_DIR = Path(__file__).parent / "_probes"
PROBES_DIR.mkdir(parents=True, exist_ok=True)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ])
    ctx = browser.new_context(
        user_agent=PC_UA,
        viewport={"width": 1440, "height": 900},
    )
    page = ctx.new_page()

    # 抓所有 XHR/JSON
    api_responses = []

    def on_response(resp):
        try:
            u = resp.url
            if "douyin.com" not in u and "iesdouyin.com" not in u:
                return
            ctype = resp.headers.get("content-type", "").lower()
            if "json" not in ctype and "graphql" not in u:
                return
            # 记录所有 JSON
            try:
                body = resp.text()[:5000]
            except Exception:
                body = ""
            api_responses.append({
                "url": u,
                "status": resp.status,
                "size": len(body),
                "preview": body[:400],
            })
        except Exception:
            pass

    page.on("response", on_response)

    t0 = time.perf_counter()
    print(f"加载 {URL_PC} (PC Web UA)")
    page.goto(URL_PC, timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    t_load = (time.perf_counter() - t0) * 1000
    print(f"  加载完成: {t_load:.0f}ms")

    # 尝试触发 hydrate: 滚动 + 等待
    for i in range(3):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(2000)
    t_total = (time.perf_counter() - t0) * 1000
    print(f"  总耗时 (含 3 次滚动+hydrate): {t_total:.0f}ms")

    html = page.content()
    html_path = PROBES_DIR / "douyin_PC_jingxuan.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML 长度: {len(html)} → {html_path.name}")

    # 1. 所有 XHR/JSON 响应
    print(f"\n=== 所有 JSON 响应 (前 30) ===")
    print(f"  总数: {len(api_responses)}")
    for r in api_responses[:30]:
        print(f"  [{r['status']}] {r['url'][:120]}")
        print(f"        size={r['size']}, preview={r['preview'][:200].strip()}")

    # 2. 过滤: 含 "follower" 或 "fans" 或 "user_info" 的 XHR
    print(f"\n=== 含粉丝/用户信息的 XHR ===")
    user_responses = [r for r in api_responses
                      if any(k in r['preview'] for k in ('follower_count', 'fans_count', 'user_info', 'follower_count_str', 'user_profile', 'other_user'))]
    for r in user_responses:
        print(f"  [{r['status']}] {r['url'][:140]}")
        print(f"        preview={r['preview'][:400].strip()}")

    # 3. HTML 中查找用户卡片相关字段
    print(f"\n=== HTML 字段扫描 ===")
    for field in ['user_info', 'user_profile', 'user_card', 'follower_count', 'follower_count_str',
                  'follower_count_v2', 'mplatform_followers', 'aweme_count', 'follower']:
        pat = re.compile(rf'"{field}"\s*:\s*"?([^",}}]{{0,30}})"?', re.IGNORECASE)
        matches = pat.findall(html)[:8]
        print(f"  {field}: {len(matches)} 处, 样本: {matches}")

    # 4. 找 HTML 中含 "大斌子" 的 user 卡片上下文
    dbz_pos = [m.start() for m in re.finditer(r'大斌子', html)]
    print(f"\n  '大斌子' 出现位置数: {len(dbz_pos)}")
    for pos in dbz_pos[:3]:
        print(f"\n  --- 大斌子 @ char {pos} 上下文 ---")
        print(html[max(0,pos-400):pos+200])

    # 5. 检查 HTML 是否有 SSR 标记 (RENDER_DATA, __INIT_PROPS__)
    print(f"\n=== SSR 标记 ===")
    for marker in ['RENDER_DATA', '__INIT_PROPS__', '__INITIAL_STATE__', '_ROUTER_DATA', '_SSR_DATA', '__NEXT_DATA__']:
        cnt = html.count(marker)
        print(f"  {marker}: {cnt} 处")

    ctx.close()
    browser.close()
