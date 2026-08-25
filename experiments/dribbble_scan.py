# -*- coding: utf-8 -*-
"""Dribbble 调研:打开相关页面截图,分析顶尖 UI 设计作品"""
import os
import time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "dribbble")
os.makedirs(OUT, exist_ok=True)

# 与开场信相关的搜索主题
URLS = [
    ("01_live_streaming", "https://dribbble.com/search/shots?q=live+streaming"),
    ("02_mobile_ui", "https://dribbble.com/search/shots?q=mobile+app+ui"),
    ("03_notification", "https://dribbble.com/search/shots?q=notification+app"),
    ("04_streamer_profile", "https://dribbble.com/search/shots?q=streamer+profile"),
    ("05_dark_ui", "https://dribbble.com/search/shots?q=dark+ui+streaming"),
    ("06_popular_today", "https://dribbble.com/shots/popular"),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    page = ctx.new_page()

    for name, url in URLS:
        path = os.path.join(OUT, f"{name}.png")
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            # 等卡片加载
            time.sleep(3.5)
            # 多次滚动触发懒加载
            for _ in range(3):
                page.mouse.wheel(0, 1600)
                time.sleep(1.2)
            page.mouse.wheel(0, -4800)  # 滚回顶部
            time.sleep(1.0)
            page.screenshot(path=path, full_page=True)
            print(f"OK {name} -> {path}")
        except Exception as e:
            print(f"FAIL {name}: {e}")

    browser.close()
print("DONE")
