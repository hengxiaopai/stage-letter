# -*- coding: utf-8 -*-
"""Dribbble 调研 v4:长等待+滚动+图片alt文本"""
import os
import json
import time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "dribbble")
os.makedirs(OUT, exist_ok=True)

SHOTS = [
    ("fanzly", "https://dribbble.com/shots/27640655-Live-Chat-Streaming-App-UI-Fanzly"),
    ("glassmorphism", "https://dribbble.com/shots/27099097-Live-Streaming-App-UI"),
    ("neon", "https://dribbble.com/shots/26163616-Live-Streaming-Mobile-App-UI-UX-Design"),
    ("purrweb", "https://dribbble.com/shots/26075849-Live-Streaming-App-Design-Concept"),
    ("finance", "https://dribbble.com/shots/27641535-Personal-Finance-App-UI-Design"),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()

    results = {}
    for name, url in SHOTS:
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            time.sleep(6)
            # 滚动加载内容
            for _ in range(4):
                page.mouse.wheel(0, 1000)
                time.sleep(1.2)
            page.mouse.wheel(0, -4000)
            time.sleep(1.5)
            data = page.evaluate("""() => {
                const result = { title: '', desc: '', alts: [], imgNames: [], body: '' };
                result.title = (document.querySelector('h1')?.textContent || '').trim().slice(0, 200);
                const metas = [...document.querySelectorAll('meta')];
                for (const m of metas) {
                    const key = m.getAttribute('name') || m.getAttribute('property') || '';
                    if (key.includes('description')) result.desc = (m.content || '').slice(0, 600);
                }
                const imgs = [...document.querySelectorAll('img')];
                result.alts = imgs.map(i => (i.alt || '').trim()).filter(a => a && a.length > 3 && a.length < 150).slice(0, 15);
                result.imgNames = imgs.map(i => (i.src || '').split('/').pop().split('?')[0]).filter(n => /dribbble|shot|teaser/i.test(n)).slice(0, 10);
                // 常见正文容器
                const cands = ['.shot-description', '.description-content', '.rich-text', '.shot-details__description', '[data-reactroot] article', '.editorial-content'];
                for (const sel of cands) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.trim().length > 20) {
                        result.body = el.innerText.trim().slice(0, 1200);
                        break;
                    }
                }
                // 全页文本中找描述段落(标题后)
                if (!result.body) {
                    const all = document.body.innerText;
                    const idx = all.indexOf('about this');
                    result.body = (idx >= 0 ? all.slice(idx, idx + 900) : all.slice(0, 900)).trim();
                }
                return result;
            }""")
            results[name] = data
            print(f"=== {name} ===")
            print("title:", data["title"][:120])
            print("desc:", data["desc"][:300])
            print("alts:", json.dumps(data["alts"], ensure_ascii=False)[:600])
            print("body:", data["body"][:500])
            print()
        except Exception as e:
            print(f"FAIL {name}: {e}")

    with open(os.path.join(OUT, "dribbble_shots_v4.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    browser.close()
print("DONE")
