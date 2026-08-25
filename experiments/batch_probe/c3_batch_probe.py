"""C3 Batch Endpoint 调研脚本骨架。

目标:找每平台"一个请求能查多个房间状态"的 API(列表页/搜索页/批量接口)。
方法:用浏览器开发者工具抓列表页/搜索页网络请求,把发现的批量 API 填进来验证。

每个平台的验证函数返回:
  {
    "url": "...",
    "method": "GET|POST",
    "batch_size": N,          # 单请求返回的房间数
    "status_available": true, # 返回里是否有 live 状态
    "auth_required": false,   # 是否需要 cookie/sign
  }

用法:
  python c3_batch_probe.py --platform bilibili [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def probe_url(url: str, method: str = "GET", json_body: dict | None = None) -> dict:
    """通用探测:返回 http 状态 + 内容类型 + 前 500 字。"""
    headers = {"User-Agent": UA, "Referer": "https://live.bilibili.com/"}
    try:
        if method.upper() == "POST":
            r = httpx.post(url, headers=headers, json=json_body, timeout=15)
        else:
            r = httpx.get(url, headers=headers, timeout=15)
        return {
            "ok": True,
            "http_status": r.status_code,
            "content_type": r.headers.get("content-type", ""),
            "body_preview": r.text[:500],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
# 每平台的候选批量端点(从浏览器抓包发现的填这里)
# ============================================================

BATCH_CANDIDATES = {
    "bilibili": [
        # 待浏览器抓包确认(wbi 签名?)
        "https://api.live.bilibili.com/xlive/web-interface/v1/index/getWebAreaList?parent_area_id=1",
    ],
    "douyin": [
        # 待确认(webcast/feed 已验证可用于 web_rid 提取,单响应 N 房间)
    ],
    "huya": [
        # ✅ 已验证(2026-08-12):120 房间/页 × 82 页,profileRoom=room_id,但列表有漏检
        "https://www.huya.com/cache.php?m=LiveList&do=getLiveListByPage&gameId=0&tagAll=0&page=1&pageSize=120",
    ],
    "douyu": [
        # ✅ 已验证(2026-08-12):页面内嵌 JSON 40 房间/页(rid+ol),但列表有漏检
        # 旧 gapi 404:https://www.douyu.com/gapi/rkc/directory/0/1.json
        "https://www.douyu.com/directory/all",
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--platform", required=True, choices=list(BATCH_CANDIDATES))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"[C3] platform={args.platform} 候选端点: {len(BATCH_CANDIDATES[args.platform])} 个")
    results = []
    for url in BATCH_CANDIDATES[args.platform]:
        print(f"\n--- 探测 {url}")
        r = probe_url(url)
        results.append({"url": url, **r})
        print(f"  http={r.get('http_status')} type={r.get('content_type')}")
        if r.get("ok") and r.get("http_status") == 200:
            body = r.get("body_preview", "")
            print(f"  预览: {body[:200]}")
        else:
            print(f"  错误: {r.get('error')}")

    if args.dry_run:
        print("\n[dry-run] 只探测候选端点,不分析 batch_size")
        return 0

    out = ROOT / "experiments" / "data" / f"c3_{args.platform}.json"
    out.write_text(json.dumps({"platform": args.platform, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
