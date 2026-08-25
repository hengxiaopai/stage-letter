"""对照测试: 抖音两个 URL 形式 + 完整 Network 抓包。

A: https://www.douyin.com/search/大斌子?type=user          (当前代码路径)
B: https://www.douyin.com/jingxuan/search/大斌子?type=general  (用户截图路径)
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
TIMEOUT_MS = 25000
WAIT_AFTER_LOAD_MS = 9000

PROBES_DIR = Path(__file__).parent / "_probes"
PROBES_DIR.mkdir(parents=True, exist_ok=True)
SSR_PROBE_JS = PROBES_DIR / "_ssr_probe.js"
SSR_PROBE_JS.write_text("""() => {
    const result = {scripts_with_sec_uid: 0, ssr_keys: [], ssr_json_samples: []};
    const scripts = document.querySelectorAll('script');
    for (const s of scripts) {
        const txt = s.textContent || '';
        if (txt.includes('sec_uid') && txt.includes('nickname')) {
            result.scripts_with_sec_uid++;
        }
        if (txt.includes('_ROUTER_DATA') || txt.includes('RENDER_DATA') ||
            txt.includes('window.__INIT_PROPS__') || txt.includes('window.__INITIAL_STATE__')) {
            result.ssr_keys.push(txt.slice(0, 50));
            // 采样前 200 字符
            const sample = txt.slice(0, 300);
            result.ssr_json_samples.push(sample);
        }
    }
    result.total_scripts = scripts.length;
    const html = document.documentElement.outerHTML;
    result.html_len = html.length;
    result.html_sec_uid_count = (html.match(/sec_uid/g) || []).length;
    result.html_nickname_count = (html.match(/nickname/g) || []).length;
    result.html_follower_count = (html.match(/follower_count/g) || []).length;
    return result;
}
""", encoding="utf-8")

DOM_PROBE_JS = SSR_PROBE_JS.parent / "_dom_probe.js"
DOM_PROBE_JS.write_text("""() => {
    const selectors = [
        'x-view.user-cell', '.user-card', '[class*="user-info"]',
        '[class*="UserCard"]', '[class*="userCard"]',
        '[class*="search-user"]', '[data-e2e="search-user-card"]'
    ];
    const cells = document.querySelectorAll(selectors.join(', '));
    let visible = 0;
    for (const c of cells) {
        if ((c.innerText || '').trim().length > 5) visible++;
    }
    return {selectors_hit: cells.length, visible_count: visible};
}
""", encoding="utf-8")


def capture(url: str, label: str) -> dict:
    """加载一个 URL, 抓所有 response / console / 提取用户数。"""
    print(f"\n{'='*70}\n[{label}] {url}\n{'='*70}")

    responses: list[dict] = []
    console_msgs: list[str] = []
    extracted_users: list[dict] = []

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

        def on_response(resp):
            try:
                u = resp.url
                if not u.startswith(("http://", "https://")):
                    return
                if not any(k in u for k in ("search", "loadmore", "/s?", "aweme", "user", "follow", "discover", "/api/", "item")):
                    return
                body_text = ""
                try:
                    ctype = resp.headers.get("content-type", "").lower()
                    if "json" in ctype or "json" in u or "graphql" in u:
                        body_text = resp.text()[:600]
                    else:
                        body_text = f"[{ctype[:30]}]"
                except Exception as e:
                    body_text = f"[err: {str(e)[:50]}]"
                responses.append({
                    "url": u[:240],
                    "status": resp.status,
                    "size": len(body_text),
                    "preview": body_text[:240],
                })
            except Exception:
                pass

        page.on("response", on_response)
        page.on("console", lambda m: console_msgs.append(f"[{m.type}] {m.text[:150]}"))

        t0 = time.perf_counter()
        try:
            page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  [goto FAIL] {e}")
        t_load = time.perf_counter() - t0

        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
        t_total = time.perf_counter() - t0

        try:
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        ssr_data_check = page.evaluate(SSR_PROBE_JS.read_text(encoding="utf-8"))
        dom_check = page.evaluate(DOM_PROBE_JS.read_text(encoding="utf-8"))

        # 数 response 中含 sec_uid+nickname 的
        for r in responses:
            preview = r.get("preview", "")
            if "sec_uid" in preview and "nickname" in preview:
                r["has_user_entity"] = preview.count('"sec_uid"')
                extracted_users.append({"source": r["url"][:80], "matches": r["has_user_entity"]})

        ctx.close()
        browser.close()

    print(f"\n  加载耗时:    {t_load*1000:.0f}ms")
    print(f"  总耗时(等渲染+滚轮): {t_total*1000:.0f}ms")
    print(f"  抓到相关 response: {len(responses)}")
    print(f"  SSR 检查: {ssr_data_check}")
    print(f"  DOM 卡片扫描: {dom_check}")

    user_responses = [r for r in responses if r.get("has_user_entity")]
    print(f"\n  含 sec_uid+nickname 的 response: {len(user_responses)}")
    for r in user_responses[:5]:
        print(f"    - {r['url']}")
        print(f"      status={r['status']}, matches={r['has_user_entity']}")
        print(f"      preview: {r['preview'][:140].strip()}")

    if console_msgs:
        print(f"\n  Console (前 5 条):")
        for m in console_msgs[:5]:
            print(f"    {m}")

    return {
        "label": label,
        "url": url,
        "t_load_ms": int(t_load*1000),
        "t_total_ms": int(t_total*1000),
        "n_responses": len(responses),
        "user_responses": len(user_responses),
        "ssr": ssr_data_check,
        "dom": dom_check,
        "responses_top10": [
            {k: v for k, v in r.items() if k != 'preview'} | {"preview": r['preview'][:120]}
            for r in user_responses[:10]
        ],
    }


if __name__ == "__main__":
    results = []
    results.append(capture(
        f"https://www.douyin.com/search/{KEYWORD}?type=user",
        "A_user_tab_current"
    ))
    results.append(capture(
        f"https://www.douyin.com/jingxuan/search/{KEYWORD}?type=general",
        "B_jingxuan_general_user_confirmed"
    ))

    out_path = SSR_PROBE_JS.parent / "douyin_probe.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n\n报告已写入: {out_path}")

    print("\n" + "="*70)
    print("总结")
    print("="*70)
    for r in results:
        print(f"\n  [{r['label']}]")
        print(f"    加载: {r['t_load_ms']}ms, 总耗时: {r['t_total_ms']}ms")
        print(f"    responses: {r['n_responses']}, 含用户实体: {r['user_responses']}")
        ssr = r['ssr']
        print(f"    SSR: scripts={ssr.get('total_scripts',0)}, html {ssr.get('html_len',0)} chars, "
              f"sec_uid×{ssr.get('html_sec_uid_count',0)}, nickname×{ssr.get('html_nickname_count',0)}, "
              f"follower_count×{ssr.get('html_follower_count',0)}")
        print(f"    SSR keys: {ssr.get('ssr_keys',[])[:3]}")
        print(f"    DOM: {r['dom']}")
