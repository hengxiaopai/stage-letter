# -*- coding: utf-8 -*-
"""Dribbble 调研 v2:监听网络请求,抓到前端真实调用的搜索接口"""
import os
import json
import time
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "..", "experiments", "data", "dribbble")
os.makedirs(OUT, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    captured = []

    def on_response(resp):
        url = resp.url
        if ("api" in url or "search" in url) and "dribbble" in url:
            try:
                body = resp.text()
                captured.append({"url": url, "status": resp.status, "body": body[:20000]})
            except Exception:
                pass

    page.on("response", on_response)
    try:
        page.goto("https://dribbble.com/search/shots?q=live+streaming+app", timeout=45000, wait_until="domcontentloaded")
        time.sleep(5)
    except Exception as e:
        print("goto err:", e)

    print("captured", len(captured), "requests")
    for c in captured[:15]:
        print("---", c["status"], c["url"][:160])
        body = c["body"]
        if body.startswith("{"):
            try:
                data = json.loads(body)
                print(json.dumps(data, ensure_ascii=False)[:1500])
            except Exception:
                print(body[:500])
        else:
            print(body[:500])

    with open(os.path.join(OUT, "dribbble_network.json"), "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)
    browser.close()
print("DONE")
