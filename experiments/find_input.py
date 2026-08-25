"""找虎牙搜索页可见的输入框(所有 input 的可见性)。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.huya.com/search", timeout=20000)
page.wait_for_timeout(5000)

# 所有 input 的位置和可见性
info = page.evaluate("""
() => {
  const out = [];
  for (const b of document.querySelectorAll('input, textarea')) {
    const r = b.getBoundingClientRect();
    const style = getComputedStyle(b);
    out.push({
      tag: b.tagName, type: b.type, placeholder: b.placeholder,
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      display: style.display, visibility: style.visibility, opacity: style.opacity
    });
  }
  return out;
}
""")
for i in info:
    print(i)
browser.close(); p.stop()
