"""分析虎牙搜索页 DOM,找结果容器。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.huya.com/search?sk=姿态", timeout=20000)
page.wait_for_timeout(8000)

js = r"""
() => {
  const out = [];
  const all = document.querySelectorAll('a');
  for (const a of all) {
    const txt = (a.innerText || '').trim();
    const href = a.href || '';
    if (txt.includes('姿态')) {
      const m = href.match(/huya\.com\/(\d{4,})/);
      if (m) out.push({href: href.slice(0, 70), txt: txt.replace(/\n/g, '|').slice(0, 70), rid: m[1]});
    }
  }
  return out.slice(0, 12);
}
"""
info = page.evaluate(js)
for i in info:
    print(i)
print("---容器 class 采样---")
js2 = r"""
() => {
  const out = [];
  const els = document.querySelectorAll('[class*="room"] a, [class*="live"] a, [class*="search"] a');
  const seen = new Set();
  for (const a of els) {
    const href = a.href || '';
    const m = href.match(/huya\.com\/(\d{4,})/);
    if (m && !seen.has(m[1])) {
      seen.add(m[1]);
      out.push({rid: m[1], cls: (a.className || '').slice(0, 50), txt: (a.innerText||'').trim().slice(0,40)});
    }
    if (out.length >= 8) break;
  }
  return out;
}
"""
for i in page.evaluate(js2):
    print(i)
browser.close()
p.stop()
