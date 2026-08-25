"""Gate 0A 信任测试:服务端边界检查。

测试场景:
  T1. 用伪造的 openid 发 → 微信能识别吗?
  T2. 不存在的 template_id → 40037 立即返回?
  T3. 伪造的 access_token → 40001?
  T4. 重放攻击:同一条消息连续发 5 次 → 微信是否限频?

这些测试帮我们理解服务端与微信之间的安全边界,
从而决定 V1 grant 模型需要多少服务端校验。
"""

from __future__ import annotations

import time

import httpx

from wechat_common import (
    WX_SEND_SUBSCRIBE_URL,
    WeChatClient,
    load_env,
    load_state,
    record_event,
    save_state,
    section,
    wait_for_user,
)


env = load_env()
APPID = env.get("WX_APPID", "")
SECRET = env.get("WX_SECRET", "")
TEMPLATE_ID = env.get("WX_TEMPLATE_LIVE_START", "")

if not APPID or not SECRET:
    print("ERROR: WX_APPID / WX_SECRET 未配置")
    raise SystemExit(1)

if not TEMPLATE_ID:
    print("ERROR: WX_TEMPLATE_LIVE_START 未配置")
    raise SystemExit(1)

client = WeChatClient(APPID, SECRET)
state = load_state()


def fmt_response(resp: dict) -> str:
    if not resp:
        return "<empty>"
    errcode = resp.get("errcode", "?")
    errmsg = resp.get("errmsg", "")
    return f"errcode={errcode}, errmsg={errmsg}"


# ============================================================
# T1: 伪造 openid
# ============================================================


def t1_fake_openid() -> None:
    section("T1 / 用伪造的 openid 发送")
    print("场景:恶意客户端拿到真实 token 后,猜测一个 openid 发送。")
    print("或:脚本攻击,穷举 openid 推送垃圾消息。")

    fake_openid = "oFAKE_FAKE_FAKE_FAKE_FAKE"
    resp = client.send_subscribe_message(
        openid=fake_openid,
        template_id=TEMPLATE_ID,
        data={
            "thing1": {"value": "T1"},
            "thing2": {"value": "测试"},
            "time3": {"value": time.strftime("%Y-%m-%d %H:%M", time.gmtime())},
        },
    )
    print(f"  响应: {fmt_response(resp)}")
    record_event(state, "trust_test_log", "T1_fake_openid", response=resp)

    if resp.get("errcode") == 40003:
        print("  ✓ 微信识别为 openid 错误,拒绝发送")
    elif resp.get("errcode") == 0:
        print("  ⚠️  居然发送成功?!微信可能没真校验(后续是否会推送?)")
    else:
        print(f"  ? 其他响应")


# ============================================================
# T2: 不存在的 template_id
# ============================================================


def t2_fake_template() -> None:
    section("T2 / 不存在的 template_id")
    real_openid = state["user"].get("openid", "oFAKE_FAKE_FAKE_FAKE_FAKE")

    resp = client.send_subscribe_message(
        openid=real_openid,
        template_id="FAKE_TEMPLATE_ID_THAT_DOES_NOT_EXIST",
        data={
            "thing1": {"value": "T2"},
            "thing2": {"value": "测试"},
            "time3": {"value": time.strftime("%Y-%m-%d %H:%M", time.gmtime())},
        },
    )
    print(f"  响应: {fmt_response(resp)}")
    record_event(state, "trust_test_log", "T2_fake_template", response=resp)

    if resp.get("errcode") == 40037:
        print("  ✓ 微信返回 40037(模板 ID 错误)")
        print("    → 我们 v0.2 文档承诺:disable 模板 ID,不影响平台 adapter。这条确认 OK")
    else:
        print(f"  ? 预期 40037,实际 {resp.get('errcode')}")


# ============================================================
# T3: 伪造 access_token
# ============================================================


def t3_fake_token() -> None:
    section("T3 / 用伪造的 access_token 直接 POST")
    print("场景:脚本尝试用假 token 调 API。")

    real_openid = state["user"].get("openid", "oFAKE_FAKE_FAKE_FAKE_FAKE")
    with httpx.Client(timeout=10.0) as c:
        resp = c.post(
            WX_SEND_SUBSCRIBE_URL,
            params={"access_token": "FAKE_FAKE_FAKE_TOKEN"},
            json={
                "touser": real_openid,
                "template_id": TEMPLATE_ID,
                "data": {
                    "thing1": {"value": "T3"},
                    "thing2": {"value": "测试"},
                    "time3": {"value": time.strftime("%Y-%m-%d %H:%M", time.gmtime())},
                },
            },
        ).json()
    print(f"  响应: {fmt_response(resp)}")
    record_event(state, "trust_test_log", "T3_fake_token", response=resp)

    if resp.get("errcode") in (40001, 42001, 40014):
        print(f"  ✓ 微信识别为 token 无效")
    else:
        print(f"  ? 预期 40001/42001/40014,实际 {resp.get('errcode')}")


# ============================================================
# T4: 重放攻击模拟
# ============================================================


def t4_replay() -> None:
    section("T4 / 重放攻击:连续发 5 次相同 message")
    real_openid = state["user"].get("openid")
    if not real_openid:
        print("  SKIP: 没有真实 openid(需先跑 wechat_grant_demo.py Step 0)")
        return

    print(f"用真实 openid ({real_openid[:8]}...) 连续发 5 次,每次间隔 1 秒")
    success_count = 0
    fail_count = 0
    for i in range(1, 6):
        resp = client.send_subscribe_message(
            openid=real_openid,
            template_id=TEMPLATE_ID,
            data={
                "thing1": {"value": f"replay-{i}"},
                "thing2": {"value": "测试"},
                "time3": {"value": time.strftime("%Y-%m-%d %H:%M", time.gmtime())},
            },
        )
        print(f"  iter {i}: {fmt_response(resp)}")
        record_event(
            state,
            "trust_test_log",
            "T4_replay",
            iteration=i,
            response=resp,
        )
        if resp.get("errcode") == 0:
            success_count += 1
        else:
            fail_count += 1
        time.sleep(1)

    print()
    print(f"  结果: 成功 {success_count} / 失败 {fail_count}")
    if success_count >= 3:
        print("  ⚠️  多次连续 send 都成功 → grant 是否存在'窗口期'?")
        print("     或:测试号没有真实限频?")
    elif fail_count >= 3:
        print("  ✓ 微信限频生效,阻止重放")


# ============================================================
# T5: 错误 template 字段格式
# ============================================================


def t5_bad_template_data() -> None:
    section("T5 / 模板 data 字段格式错误")
    real_openid = state["user"].get("openid", "oFAKE_FAKE_FAKE_FAKE_FAKE")

    # thing1 超过 20 字
    resp = client.send_subscribe_message(
        openid=real_openid,
        template_id=TEMPLATE_ID,
        data={
            "thing1": {"value": "x" * 100},  # 故意超长
            "thing2": {"value": "测试"},
            "time3": {"value": time.strftime("%Y-%m-%d %H:%M", time.gmtime())},
        },
    )
    print(f"  响应(超长字段): {fmt_response(resp)}")
    record_event(state, "trust_test_log", "T5_bad_data_long", response=resp)

    # time3 格式错误
    resp = client.send_subscribe_message(
        openid=real_openid,
        template_id=TEMPLATE_ID,
        data={
            "thing1": {"value": "T5"},
            "thing2": {"value": "测试"},
            "time3": {"value": "2026/08/01 8pm"},  # 错误格式
        },
    )
    print(f"  响应(时间格式错): {fmt_response(resp)}")
    record_event(state, "trust_test_log", "T5_bad_data_time", response=resp)


# ============================================================
# 主流程
# ============================================================


def main() -> None:
    section("Gate 0A 信任测试")
    print("验证服务端与微信之间的安全边界。")
    print()
    wait_for_user("继续按回车开始(随时 Ctrl+C 中断)")

    t1_fake_openid()
    t2_fake_template()
    t3_fake_token()
    t4_replay()
    t5_bad_template_data()

    section("信任测试完成")
    print(f"详细日志: data/grant_state.json (trust_test_log 字段)")
    print()
    print("把结果填入 reports/wechat_grant.md 的信任测试小节")


if __name__ == "__main__":
    main()