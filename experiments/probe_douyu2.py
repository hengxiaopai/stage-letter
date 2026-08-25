"""斗鱼搜索结果 DOM 结构探测。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.douyu.com/search/雨神", timeout=20000)
page.wait_for_timeout(8000)

# 所有含 douyu.com/数字 的链接
links = page.evaluate("""
() => {
  const out = [];
  for (const a of document.querySelectorAll('a')) {
    const m = (a.href||'').match(/douyu\.com\/(\\d+)/);
    if (m) {
      out.push({rid: m[1], cls: (a.className||'').slice(0,40), txt: (a.innerText||'').trim().replace(/\\n/g,'|').slice(0,50)});
      if (out.length >= 10) break;
    }
  }
  return out;
}
""")
for l in links:
    print(l)
print("---")
# 也看 title
print("title:", page.title())
browser.close(); p.stop()
