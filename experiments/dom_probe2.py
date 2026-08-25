"""探测虎牙搜索页的输入框和按钮交互。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.huya.com/search", timeout=20000)
page.wait_for_timeout(4000)

# 找输入框
boxes = page.evaluate("""
() => {
  const out = [];
  for (const b of document.querySelectorAll('input')) {
    out.push({type: b.type, placeholder: b.placeholder, cls: (b.className||'').slice(0,40), id: b.id});
  }
  return out;
}
""")
print("输入框:", boxes)
# 找搜索按钮
btns = page.evaluate("""
() => {
  const out = [];
  for (const b of document.querySelectorAll('button')) {
    out.push({txt: (b.innerText||'').trim().slice(0,10), cls: (b.className||'').slice(0,40)});
  }
  return out.slice(0, 10);
}
""")
print("按钮:", btns)

# 尝试交互: 填 input + 点按钮/回车
box = page.query_selector("input[type='search']") or page.query_selector("input")
if box:
    box.fill("姿态")
    page.wait_for_timeout(500)
    box.press("Enter")
    page.wait_for_timeout(6000)
    has = page.evaluate("document.body.innerText.includes('姿态')")
    print("回车后页面含姿态:", has)
    # 找结果
    cards = page.query_selector_all("a.new-clickstat")
    print("结果卡数量:", len(cards))
    for c in cards[:5]:
        print("  ", (c.inner_text() or "").strip().replace("\n", "|")[:60])
browser.close()
p.stop()
