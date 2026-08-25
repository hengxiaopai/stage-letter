"""
Probe the WeChat sandbox account to see exactly what subscription-message
capabilities are available. Uses raw httpx so we don't depend on extra
methods on WeChatClient.

We try:
  1) gettemplate (我的模板) - list existing templates
  2) getcategory (类目) - categories we can use
  3) getpubtemplatetitles (公共模板) - public titles
  4) addtemplate (选用公共模板) - use a placeholder tid to see the error code
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from wechat_common import WeChatClient, load_env


def show(label: str, resp: dict) -> None:
    errcode = resp.get("errcode", "?")
    errmsg = resp.get("errmsg", "")
    print(f"\n=== {label} ===")
    print(f"errcode = {errcode}")
    print(f"errmsg  = {errmsg}")
    if "data" in resp:
        d = resp["data"]
        if isinstance(d, list):
            print(f"data    = list[{len(d)}]")
            for i, item in enumerate(d[:5]):
                print(f"  [{i}] {json.dumps(item, ensure_ascii=False)[:200]}")
            if len(d) > 5:
                print(f"  ... and {len(d)-5} more")
        elif isinstance(d, dict):
            print(f"data    = dict, keys: {list(d.keys())}")
            for k, v in d.items():
                s = json.dumps(v, ensure_ascii=False)
                print(f"  {k}: {s[:200]}")
    print("--- raw (truncated) ---")
    print(json.dumps(resp, ensure_ascii=False)[:500])


def main() -> int:
    env = load_env()
    appid = env.get("WX_APPID")
    secret = env.get("WX_SECRET")
    if not appid or not secret:
        print(f"ERROR: appid/secret not in env, keys={list(env)}", file=sys.stderr)
        return 2

    cli = WeChatClient(appid, secret)
    token = cli.get_access_token()
    print(f"access_token (first 16): {token[:16]}...")
    base = "https://api.weixin.qq.com/wxaapi/newtmpl"

    # 1. 已有模板
    r = httpx.get(f"{base}/gettemplate", params={"access_token": token}, timeout=10).json()
    show("gettemplate (我的模板)", r)

    # 2. 类目
    r = httpx.get(f"{base}/getcategory", params={"access_token": token}, timeout=10).json()
    show("getcategory (类目)", r)

    # 3. 公共模板标题
    r = httpx.get(
        f"{base}/getpubtemplatetitles",
        params={"access_token": token, "kid": 0, "limit": 20},
        timeout=10,
    ).json()
    show("getpubtemplatetitles (公共模板-全部)", r)

    # 4. 若有公共模板,挑第一个,试 "选用" -> 能否正常 addtemplate
    if r.get("errcode") == 0 and isinstance(r.get("data"), list) and r["data"]:
        first = r["data"][0]
        tid = first.get("tid")
        print(f"\n=== addtemplate dry-run with tid={tid} ({first.get('title')!r}) ===")
        # Step 1: get keywords for that template
        kw_resp = httpx.get(
            f"{base}/getpubtemplatekeywords",
            params={"access_token": token, "tid": tid},
            timeout=10,
        ).json()
        show("getpubtemplatekeywords (关键词列表)", kw_resp)
        kid_list = []
        if kw_resp.get("errcode") == 0:
            for kw in kw_resp.get("data", []):
                kid_list.append(kw.get("kid"))
        # Step 2: try to adopt
        if kid_list:
            adopted = httpx.post(
                f"{base}/addtemplate",
                params={"access_token": token},
                json={"tid": tid, "kidList": kid_list, "sceneDesc": "StageLetter probe"},
                timeout=10,
            ).json()
            show("addtemplate (选用)", adopted)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
