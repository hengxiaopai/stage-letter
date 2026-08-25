"""用 playwright 监听虎牙搜索的真实 API 请求。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")

captured = []
def on_response(resp):
    url = resp.url
    if ("search" in url or "Search" in url) and "huya" in url:
        captured.append(url[:200])

page.on("response", on_response)
page.goto("https://www.huya.com/search?sk=姿态", timeout=20000)
page.wait_for_timeout(6000)

print("捕获的搜索 API 请求:")
for u in captured:
    print("  ", u)
browser.close()
p.stop()
