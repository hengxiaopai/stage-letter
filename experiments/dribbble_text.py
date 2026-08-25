# -*- coding: utf-8 -*-
"""Dribbble 调研:提取搜索结果的 shot 标题/简介/标签文本,分析设计趋势"""
import os
import json
import time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "dribbble")
os.makedirs(OUT, exist_ok=True)

URLS = [
    ("live_streaming", "https://dribbble.com/search/shots?q=live+streaming"),
    ("mobile_ui", "https://dribbble.com/search/shots?q=mobile+app+ui"),
    ("notification", "https://dribbble.com/search/shots?q=notification+app"),
    ("streamer_profile", "https://dribbble.com/search/shots?q=streamer+profile"),
    ("dark_ui", "https://dribbble.com/search/shots?q=dark+ui+streaming"),
    ("popular", "https://dribbble.com/shots/popular"),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
    )
    page = ctx.new_page()

    all_data = {}
    for name, url in URLS:
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            time.sleep(3.0)
            for _ in range(3):
                page.mouse.wheel(0, 1600)
                time.sleep(1.0)
            # 提取 shot 卡片文本
            shots = page.evaluate("""() => {
                const items = [];
                // Dribbble shot card 结构: a.shot-thumbnail / li > a
                const anchors = document.querySelectorAll('a.shot-thumbnail, a[href*="/shots/"]');
                const seen = new Set();
                for (const a of anchors) {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/shots\\/([\\w-]+)/);
                    if (!m || seen.has(m[1])) continue;
                    seen.add(m[1]);
                    const title = (a.getAttribute('title') || a.querySelector('.shot-title')?.textContent || '').trim();
                    // 取整个卡片文本
                    const card = a.closest('li, div') || a;
                    const text = (card.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 300);
                    items.push({ id: m[1], title, text });
                }
                return items.slice(0, 20);
            }""")
            all_data[name] = shots
            print(f"OK {name}: {len(shots)} shots")
        except Exception as e:
            print(f"FAIL {name}: {e}")
            all_data[name] = []

    browser.close()

with open(os.path.join(OUT, "dribbble_shots.json"), "w", encoding="utf-8") as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)
print("SAVED")
