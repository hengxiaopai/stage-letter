"""虎牙搜索切「主播」tab 再搜,验证能否按昵称搜到姿态。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.huya.com/search", timeout=20000)
page.wait_for_timeout(4000)

# 找"主播" tab 并点击
clicked = page.evaluate("""
() => {
  const els = document.querySelectorAll('span.clickstat, div.clickstat, a.clickstat');
  for (const el of els) {
    if ((el.innerText||'').trim() === '主播') {
      el.click();
      return el.outerHTML.slice(0, 100);
    }
  }
  return null;
}
""")
print("点击主播tab:", clicked)
page.wait_for_timeout(2000)

# 输入关键词搜索
box = None
for candidate in page.query_selector_all("input[type='text']"):
    r = candidate.bounding_box()
    if r and r["width"] > 50 and r["height"] > 20:
        box = candidate
        break
if box:
    box.click()
    page.wait_for_timeout(300)
    box.fill("姿态")
    box.press("Enter")
    page.wait_for_timeout(7000)
    print("=== 主播 tab 搜索结果 ===")
    cards = page.query_selector_all("a.new-clickstat")
    for c in cards[:10]:
        txt = (c.inner_text() or "").strip().replace("\n", "|")
        import re
        m = re.search(r"huya\.com/(\d+)", c.get_attribute("href") or "")
        print(f"  rid={m.group(1) if m else '?'} | {txt[:70]}")
browser.close(); p.stop()
