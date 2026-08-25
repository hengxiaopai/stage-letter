"""探测斗鱼搜索页。"""
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0")
# 斗鱼搜索几种 URL 形态
for url in ["https://www.douyu.com/search/雨神?type=live",
            "https://www.douyu.com/search/雨神"]:
    try:
        page.goto(url, timeout=20000)
        page.wait_for_timeout(6000)
        has = page.evaluate("document.body.innerText.includes('雨神')")
        title = page.title()
        cards = page.evaluate("""
        () => {
          const out = [];
          for (const a of document.querySelectorAll('a[data-rid]')) {
            out.push({rid: a.getAttribute('data-rid'), txt: (a.innerText||'').trim().replace(/\\n/g,'|').slice(0,50)});
            if (out.length >= 5) break;
          }
          return out;
        }
        """)
        print(f"{url} | title={title} | 含雨神={has} | cards={len(cards)}")
        for c in cards:
            print("  ", c)
        if cards:
            break
    except Exception as e:
        print(f"{url} ERR {str(e)[:60]}")
browser.close(); p.stop()
