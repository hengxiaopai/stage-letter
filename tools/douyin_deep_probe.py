"""深挖: 抓 B 路径完整 HTML, 定位 sec_uid/nickname 所在的 <script>, 打印实际 JSON 结构。"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

KEYWORD = "大斌子"
URL = f"https://www.douyin.com/jingxuan/search/{KEYWORD}?type=general"

PROBES_DIR = Path(__file__).parent / "_probes"
PROBES_DIR.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ])
    ctx = browser.new_context(
        user_agent=MOBILE_UA,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
    )
    page = ctx.new_page()
    t0 = time.perf_counter()
    page.goto(URL, timeout=25000, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)

    # 抓含 sec_uid 的 script
    sample_script = page.evaluate("""
        () => {
            const scripts = document.querySelectorAll('script');
            const hits = [];
            for (let i = 0; i < scripts.length; i++) {
                const txt = scripts[i].textContent || '';
                if (txt.includes('sec_uid') && txt.includes('nickname')) {
                    hits.push({
                        idx: i,
                        len: txt.length,
                        preview: txt.slice(0, 200),
                        end_preview: txt.slice(-200),
                    });
                }
            }
            return hits;
        }
    """)
    print("含 sec_uid+nickname 的 script:")
    for h in sample_script:
        print(f"  script[{h['idx']}]: {h['len']} chars")
        print(f"    head: {h['preview'][:150]}")
        print(f"    tail: {h['end_preview'][:150]}")
        print()

    # 抓完整 HTML 保存
    html = page.content()
    html_path = PROBES_DIR / "douyin_B_full.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"完整 HTML 已保存: {html_path} ({len(html)} chars)")

    # 抓 nickname 出现位置 5 处
    nicknames = re.findall(r'"nickname"\s*:\s*"([^"]{2,40})"', html)
    print(f"\nHTML 中所有 nickname (前 15): {nicknames[:15]}")
    sec_uids = re.findall(r'"sec_uid"\s*:\s*"([A-Za-z0-9_\-]{10,80})"', html)
    print(f"\nHTML 中所有 sec_uid (前 10): {sec_uids[:10]}")
    fans = re.findall(r'"follower_count"\s*:\s*(\d{1,15})', html)
    print(f"\nHTML 中所有 follower_count (前 10): {fans[:10]}")

    # 提取一组完整的 user 实体 — 用 regex 找 "用户对象" 上下文
    # 抖音 SSR 一般结构: {"user_info":{"nickname":"...","sec_uid":"...","follower_count":...},...}
    # 或 {"user":{"nickname":"...","sec_uid":"...","follower_count":...}}
    # 抓所有可能容器
    patterns = [
        # 标准 user_info 块 (昵称/UID/粉丝/关注 一起)
        (r'"user_info"\s*:\s*\{[^{}]{0,800}"nickname"\s*:\s*"([^"]{1,40})"[^{}]{0,800}"sec_uid"\s*:\s*"([A-Za-z0-9_\-]{10,80})"[^{}]{0,1500}"follower_count"\s*:\s*(\d+)', "user_info block"),
        # user 块
        (r'"user"\s*:\s*\{[^{}]{0,800}"nickname"\s*:\s*"([^"]{1,40})"[^{}]{0,800}"sec_uid"\s*:\s*"([A-Za-z0-9_\-]{10,80})"[^{}]{0,1500}"follower_count"\s*:\s*(\d+)', "user block"),
    ]

    for pat, name in patterns:
        matches = re.findall(pat, html)
        print(f"\n  [{name}] 命中 {len(matches)} 组:")
        for m in matches[:5]:
            print(f"    nickname={m[0]!r}, sec_uid={m[1][:20]}..., fans={m[2]}")

    # 进一步: 抓所有 出现 "nickname" 的 script
    scripts_with_nick = page.evaluate("""
        () => {
            const out = [];
            const scripts = document.querySelectorAll('script');
            for (let i = 0; i < scripts.length; i++) {
                const txt = scripts[i].textContent || '';
                if (txt.includes('nickname')) {
                    out.push({idx: i, len: txt.length, has_sec_uid: txt.includes('sec_uid')});
                }
            }
            return out;
        }
    """)
    print(f"\n含 nickname 的 script 概览:")
    for s in scripts_with_nick:
        print(f"  script[{s['idx']}]: {s['len']} chars, has_sec_uid={s['has_sec_uid']}")

    ctx.close()
    browser.close()

print(f"\n总耗时: {(time.perf_counter()-t0)*1000:.0f}ms")
