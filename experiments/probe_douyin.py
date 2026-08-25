"""探测抖音搜索页 DOM。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
page.goto("https://www.douyin.com/search/天蚕土豆?type=user", timeout=25000)
page.wait_for_timeout(10000)

# 页面文本包含关键词?
has = page.evaluate("document.body.innerText.includes('天蚕土豆')")
print("页面含关键词:", has)
# 找含关键词的元素
items = page.evaluate("""
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (walker.nextNode()) {
    const el = walker.currentNode;
    const txt = (el.innerText || '').trim();
    if (txt.includes('天蚕土豆') && txt.length < 80 && el.tagName === 'A') {
      out.push({cls: (el.className||'').slice(0,50), txt: txt.replace(/\\n/g,'|').slice(0,60), href: (el.href||'').slice(0,60)});
    }
  }
  return out.slice(0, 8);
}
""")
for i in items:
    print(i)
# 通用: 所有 img alt 含关键词的
imgs = page.evaluate("""
() => {
  const out = [];
  for (const img of document.querySelectorAll('img')) {
    const alt = img.alt || '';
    if (alt.includes('天蚕土豆') || (img.parentElement && (img.parentElement.innerText||'').includes('天蚕土豆') && (img.parentElement.innerText||'').length < 80)) {
      out.push({alt: alt.slice(0,30), src: (img.src||'').slice(0,60)});
    }
  }
  return out.slice(0, 8);
}
""")
for i in imgs:
    print("IMG:", i)
browser.close(); p.stop()
