"""验证抖音 web_rid 列表,输出每个的状态(只保留 ONLINE)。
用法: python verify_douyin.py <web_rid1> <web_rid2> ...
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_adapters.douyin.adapter import DouyinAdapter


def main():
    if len(sys.argv) < 2:
        print("用法: python verify_douyin.py <web_rid> [...]")
        sys.exit(1)
    rids = sys.argv[1:]
    a = DouyinAdapter()
    results = []
    for rid in rids:
        s = a.get_status(rid)
        state = s.get("state", "?")
        ok = s.get("ok", False)
        nickname = s.get("nickname", "")
        title = s.get("title", "")
        print(f"{rid} -> {state} | {nickname[:20]} | {title[:35]}")
        results.append({"web_rid": rid, "state": state, "nickname": nickname,
                        "title": title, "ok": ok, "errcode": s.get("errcode")})
    online = [r for r in results if r["state"] == "ONLINE"]
    print(f"\n=== ONLINE: {len(online)}/{len(results)} ===")
    for r in online:
        print(f"  {r['web_rid']}  {r['nickname'][:20]}")
    sys.exit(0 if len(online) >= 5 else 2)


if __name__ == "__main__":
    main()
