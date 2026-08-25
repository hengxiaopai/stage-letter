# -*- coding: utf-8 -*-
"""Dribbble 调研 v3:直接打开具体 shot 详情页,抓标题+描述+标签"""
import os
import json
import time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "dribbble")
os.makedirs(OUT, exist_ok=True)

SHOTS = [
    ("live_streaming_fanzly", "https://dribbble.com/shots/27640655-Live-Chat-Streaming-App-UI-Fanzly"),
    ("live_streaming_glassmorphism", "https://dribbble.com/shots/27099097-Live-Streaming-App-UI"),
    ("live_streaming_neon", "https://dribbble.com/shots/26163616-Live-Streaming-Mobile-App-UI-UX-Design"),
    ("live_streaming_purrweb", "https://dribbble.com/shots/26075849-Live-Streaming-App-Design-Concept"),
    ("gaming_live_app", "https://dribbble.com/shots/27642547-Modelyard-AI-Model-Monitoring-Platform"),  # 备用
    ("personal_finance_app", "https://dribbble.com/shots/27641535-Personal-Finance-App-UI-Design"),
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
            time.sleep(4)
            data = page.evaluate("""() => {
                const g = (sel) => document.querySelector(sel)?.textContent?.trim() || '';
                const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
                const ogDesc = document.querySelector('meta[property="og:description"]')?.content || '';
                const tags = [...document.querySelectorAll('a.tag')].map(a => a.textContent.trim()).slice(0, 12);
                // shot 正文描述
                let body = '';
                const bodySel = document.querySelector('.shot-description, [data-reactroot] .rich-text, .shot-details');
                if (bodySel) body = bodySel.innerText.trim().slice(0, 1200);
                const title = g('h1') || g('.shot-title');
                return {
                    title: title.slice(0, 200),
                    metaDesc: metaDesc.slice(0, 800),
                    ogDesc: ogDesc.slice(0, 800),
                    tags,
                    body: body.slice(0, 1200),
                };
            }""")
            results[name] = data
            print(f"=== {name} ===")
            print("title:", data["title"][:120])
            print("desc:", (data["ogDesc"] or data["metaDesc"])[:500])
            print("tags:", data["tags"])
            print("body:", data["body"][:600])
            print()
        except Exception as e:
            print(f"FAIL {name}: {e}")

    with open(os.path.join(OUT, "dribbble_shots_detail.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    browser.close()
print("DONE")
