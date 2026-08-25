"""
Verify that WX_TEMPLATE_LIVE_START (the template id the user just obtained
from their REAL mini-program account) belongs to the AppID in .env.

Checks:
  1. gettemplate  - does our account already have this template?
  2. If not listed, error out clearly telling which AppID owns it.
  3. If listed, show the template's keyword/field structure so we can build
     the correct payload for subscribe/send.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from wechat_common import WeChatClient, load_env

TEMPLATE_ID = "VehDuOW2xRXubcWgFvcgnFnp42wdA3uesHpjfmBP-Cs"


def main() -> int:
    env = load_env()
    appid = env.get("WX_APPID")
    secret = env.get("WX_SECRET")
    print(f"AppID from env: {appid} (末4位 {appid[-4:] if appid else '??'})")
    print(f"Template from env: {env.get('WX_TEMPLATE_LIVE_START', '')}")

    if env.get("WX_TEMPLATE_LIVE_START") != TEMPLATE_ID:
        print("ERROR: .env template id != expected. Fix .env first.", file=sys.stderr)
        return 2

    cli = WeChatClient(appid, secret)
    tok = cli.get_access_token()
    print(f"access_token (first 16): {tok[:16]}...")

    # 1. List templates
    r = httpx.get(
        "https://api.weixin.qq.com/wxaapi/newtmpl/gettemplate",
        params={"access_token": tok},
        timeout=10,
    ).json()
    print("\n=== gettemplate (我的模板) ===")
    print(f"errcode={r.get('errcode')} errmsg={r.get('errmsg')}")
    tpls = r.get("data") or []
    print(f"模板数量: {len(tpls)}")
    found = None
    for t in tpls:
        tid = t.get("priTmplId") or t.get("template_id") or ""
        mark = "  <<<< 目标" if tid == TEMPLATE_ID else ""
        print(f"  tid={tid}  title={t.get('title')!r}  content={str(t.get('content'))[:120]}{mark}")
        if tid == TEMPLATE_ID:
            found = t
    if found is None:
        print("\n❌ 目标模板不在当前 AppID 的模板列表中!")
        print("   → 说明:这个模板 ID 属于【另一个 AppID】(正式号),不是 .env 里的测试号。")
        print("   → 处理:请把正式号的 AppID + AppSecret 发来,我会更新 .env 后重试。")
        return 1

    print("\n✅ 目标模板属于当前 AppID,可以直接用于 subscribe/send!")
    print(f"   priTmplId = {found.get('priTmplId')}")
    print(f"   title     = {found.get('title')}")
    print(f"   content   = {found.get('content')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
