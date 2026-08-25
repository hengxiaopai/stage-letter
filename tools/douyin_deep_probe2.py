"""深挖 #2: 找 follower_count 真实字段 + 对比 A/B 路径的 user 列表。

1. 全 HTML 搜各种粉丝数命名变体
2. 看 A 路径 (/search/{kw}?type=user) 的 HTML 有没有"大斌子"在 nickname 里
3. 提取 script[111] 完整结构
"""
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

PROBES_DIR = Path(__file__).parent / "_probes"
PROBES_DIR.mkdir(parents=True, exist_ok=True)


def load_url(url: str, label: str) -> dict:
    print(f"\n{'='*70}\n[{label}] {url}\n{'='*70}")
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
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        t_load = (time.perf_counter() - t0) * 1000

        html = page.content()
        html_path = PROBES_DIR / f"douyin_{label}.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"  加载: {t_load:.0f}ms, HTML {len(html)} chars → {html_path.name}")

        # 1. 各种粉丝数字段
        field_variants = {
            "follower_count_str": r'"follower_count_str"\s*:\s*"([^"]{0,30})"',
            "follower_count": r'"follower_count"\s*:\s*(\d{1,15})',
            "fans_count": r'"fans_count"\s*:\s*(\d{1,15})',
            "follower": r'"follower"\s*:\s*(\d{1,15})',
            "total_fans": r'"total_fans"\s*:\s*(\d{1,15})',
        }
        for name, pat in field_variants.items():
            matches = re.findall(pat, html)
            print(f"  {name}: {len(matches)} 处, 样本={matches[:8]}")

        # 2. 大斌子 出现在 HTML 哪里
        dbz_count = html.count("大斌子")
        print(f"\n  '大斌子' 出现次数: {dbz_count}")
        if dbz_count > 0:
            idx = html.find("大斌子")
            print(f"  第 1 处上下文 (前 200 / 后 200):")
            print(f"    {html[max(0,idx-200):idx]}|大斌子|{html[idx+3:idx+200]}")

        # 3. 找包含"大斌子"且包含 sec_uid 的 script 块
        scripts = page.evaluate("""
            () => {
                const out = [];
                const ss = document.querySelectorAll('script');
                for (let i = 0; i < ss.length; i++) {
                    const t = ss[i].textContent || '';
                    if (t.includes('大斌子') && t.includes('sec_uid')) {
                        out.push({idx: i, len: t.length, dbz: (t.match(/大斌子/g) || []).length, sec: (t.match(/sec_uid/g) || []).length});
                    }
                }
                return out;
            }
        """)
        print(f"\n  含 '大斌子' + 'sec_uid' 的 script:")
        for s in scripts:
            print(f"    script[{s['idx']}]: {s['len']} chars, 大斌子×{s['dbz']}, sec_uid×{s['sec']}")

        # 4. 找 nickname 紧挨 "大斌子" 的样本
        all_nicknames = re.findall(r'"nickname"\s*:\s*"([^"]{1,40})"', html)
        nick_with_dbz = [n for n in all_nicknames if "大斌" in n or "斌" in n]
        print(f"\n  含'斌'的 nickname (从 {len(all_nicknames)} 个里): {nick_with_dbz[:10]}")

        # 5. 提取典型 user 对象
        # 抖音实际 user 列表通常长这样:
        # {"user":{"nickname":"大斌子","sec_uid":"MS4w...","follower_count":4682000,"avatar_thumb":{...}}}
        # 或 {"user_info":{...}}
        # 也可能是 {"users":[{...}]} 数组形式
        # 用一个更宽松的 regex: 找 (大斌子 OR 类似昵称) 前后 1500 字符
        if nick_with_dbz:
            nick = nick_with_dbz[0]
            escaped = re.escape(nick)
            m = re.search(rf'"{escaped}"[^\n]{{0,3000}}', html)
            if m:
                print(f"\n  首个匹配昵称 '{nick}' 的上下文 (3000 chars):")
                ctx_txt = m.group(0)
                print(ctx_txt[:2000])
                # 找 sec_uid
                sm = re.search(r'"sec_uid"\s*:\s*"([A-Za-z0-9_\-]{20,80})"', ctx_txt)
                if sm:
                    print(f"\n  sec_uid: {sm.group(1)}")
                # 找所有粉丝数变体
                for fn in ["follower_count", "follower_count_str", "fans_count", "total_fans"]:
                    fm = re.search(rf'"{fn}"\s*:\s*"?(\d+(?:\.\d+)?[wW万千]?)"?', ctx_txt)
                    if fm:
                        print(f"  {fn}: {fm.group(0)}")

        ctx.close()
        browser.close()
    return {}


if __name__ == "__main__":
    load_url(
        f"https://www.douyin.com/search/{KEYWORD}?type=user",
        "A_user_tab",
    )
    load_url(
        f"https://www.douyin.com/jingxuan/search/{KEYWORD}?type=general",
        "B_jingxuan_general",
    )
