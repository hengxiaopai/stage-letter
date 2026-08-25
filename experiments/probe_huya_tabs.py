"""探测虎牙搜索页的 tab 结构(房间/主播分类)。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.huya.com/search", timeout=20000)
page.wait_for_timeout(4000)

# 找 tab(含"主播"/"房间"/"直播"文字的元素)
tabs = page.evaluate("""
() => {
  const out = [];
  for (const el of document.querySelectorAll('a, span, div, li')) {
    const t = (el.innerText || '').trim();
    if (t.length <= 6 && /主播|房间|直播|用户/.test(t) && t.length >= 2) {
      const r = el.getBoundingClientRect();
      if (r.width > 20) {
        out.push({tag: el.tagName, txt: t, href: (el.href||'').slice(0,80), cls: (el.className||'').slice(0,40)});
      }
    }
  }
  return out.slice(0, 10);
}
""")
for t in tabs:
    print(t)
browser.close(); p.stop()
