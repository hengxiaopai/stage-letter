"""Gate 0A 主实验:微信 grant 模型真机验证。

跑 6 个实验场景,验证 v0.2 grant 模型假设:
  1. 授权一次 → 第 1 条发送成功
  2. 不重新授权 → 第 2 条发送失败
  3. 重新授权 → 第 3 条发送成功
  4. 用户勾选"总是保持以上选择" → 实际行为?
  5. 客户端伪造 accept → 微信能否识别?
  6. 用户拒收某模板 → 仍能转站内?

每个实验完成后按提示继续,所有结果写入 data/grant_state.json。

前置条件:详见 ../WECHAT-TEST-ACCOUNT.md
"""

from __future__ import annotations

import json
import time

from wechat_common import (
    WeChatClient,
    WeChatError,
    explain_error,
    load_env,
    load_state,
    record_event,
    save_state,
    section,
    wait_for_user,
)


# ============================================================
# 初始化
# ============================================================

env = load_env()
APPID = env.get("WX_APPID", "")
SECRET = env.get("WX_SECRET", "")
TEMPLATE_ID = env.get("WX_TEMPLATE_LIVE_START", "")

if not APPID or not SECRET:
    print("ERROR: WX_APPID / WX_SECRET 未配置。")
    print("请按 ../WECHAT-TEST-ACCOUNT.md 注册测试号,然后在 experiments/.env 中填入。")
    raise SystemExit(1)

if not TEMPLATE_ID:
    print("ERROR: WX_TEMPLATE_LIVE_START 未配置。")
    print("详见 ../WECHAT-TEST-ACCOUNT.md §2 申请订阅消息模板。")
    raise SystemExit(1)

client = WeChatClient(APPID, SECRET)
state = load_state()


# ============================================================
# 工具
# ============================================================


def fmt_response(resp: dict) -> str:
    """格式化微信响应。"""
    if not resp:
        return "<empty>"
    errcode = resp.get("errcode", "?")
    errmsg = resp.get("errmsg", "")
    msgid = resp.get("msgid", "")
    extra = f", msgid={msgid}" if msgid else ""
    return f"errcode={errcode} ({explain_error(errcode)}){extra}"


def reset_grant(template_id: str) -> None:
    """重置某个 template 的 grant 计数(实验开始前调用)。"""
    state["grants"][template_id] = {
        "granted_count": 0,
        "consumed_count": 0,
        "history": [],
    }
    save_state(state)


def increment_granted(template_id: str, source: str) -> None:
    """模拟客户端回调:用户 accept,granted +1。"""
    state["grants"][template_id]["granted_count"] += 1
    state["grants"][template_id]["history"].append(
        {
            "type": "granted",
            "source": source,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    save_state(state)


def increment_consumed(template_id: str, response: dict) -> None:
    """服务端真实 send 后,consumed +1。"""
    state["grants"][template_id]["consumed_count"] += 1
    state["grants"][template_id]["history"].append(
        {
            "type": "consumed",
            "response": response,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    save_state(state)


def try_send(openid: str, template_id: str, label: str) -> dict:
    """发送一条订阅消息,返回微信原始响应。

    模板"直播开播通知"有 5 个字段(2026-08-12 从正式号 gettemplate 确认):
      thing1 达人名称 / thing2 直播间名称 / time3 开播时间
      thing5 直播主题 / thing6 直播间活动
    微信要求全字段填充,缺一不可。
    """
    now = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    data = {
        "thing1": {"value": label[:20]},  # 达人名称
        "thing2": {"value": "测试直播间"},  # 直播间名称
        "time3": {"value": now},  # 开播时间
        "thing5": {"value": "Gate0A-测试"},  # 直播主题
        "thing6": {"value": "无"},  # 直播间活动
    }
    resp = client.send_subscribe_message(
        openid=openid, template_id=template_id, data=data
    )
    print(f"  响应: {fmt_response(resp)}")
    return resp


# ============================================================
# Step 0: 微信登录
# ============================================================


def step0_login() -> str:
    section("Step 0 / 微信登录")
    openid = state["user"].get("openid")
    if openid:
        print(f"已存在 openid: {openid[:8]}...{openid[-4:]}")
        print("(如需重新登录,删除 data/grant_state.json 后重跑)")
        return openid

    print("需要先用 wx.login 拿 code,然后调用 code2session 换 openid。")
    print()
    print("操作步骤:")
    print("  1. 打开微信开发者工具,用你的测试号 APPID 登录")
    print("  2. 新建/打开项目,在 app.js 的 onLaunch 里加:")
    print("       wx.login({ success: r => console.log('CODE:', r.code) })")
    print("  3. 在开发者工具'控制台'里能看到 code(5 分钟内有效)")
    print()

    while True:
        code = input("请粘贴 code (输入 q 退出): ").strip()
        if code.lower() == "q":
            raise SystemExit(0)
        if not code:
            continue
        try:
            user_info = client.code2session(code)
            break
        except WeChatError as e:
            print(f"  ✗ {e}")
            print("  请重新拿 code(code 5 分钟内有效,且只能使用一次)")

    state["user"] = {
        "openid": user_info["openid"],
        "unionid": user_info.get("unionid"),
    }
    save_state(state)
    openid = user_info["openid"]
    print(f"  ✓ 拿到 openid: {openid[:8]}...{openid[-4:]}")
    print(f"    unionid: {user_info.get('unionid') or '(空)'}")
    return openid


# ============================================================
# 实验 1: 授权一次,发第 1 条
# ============================================================


def exp1_first_send(openid: str) -> None:
    section("实验 1 / 授权一次,立即发第 1 条 (期望: 成功)")
    reset_grant(TEMPLATE_ID)

    wait_for_user(
        "在测试小程序里触发 wx.requestSubscribeMessage:\n"
        "  wx.requestSubscribeMessage({ tmplIds: ['" + TEMPLATE_ID + "'] })\n"
        "用户点'允许'后,继续。"
    )

    increment_granted(TEMPLATE_ID, source="wx.requestSubscribeMessage.accept")
    print("  ✓ 模拟 grant +1(用户在客户端调 request-grant 后,服务端 granted +1)")

    print("尝试发送第 1 条...")
    resp = try_send(openid, TEMPLATE_ID, "测试主播A-首次授权")

    if resp.get("errcode") == 0:
        increment_consumed(TEMPLATE_ID, resp)
        print("  ✓ 第 1 条发送成功,真机应该收到推送")
    else:
        print(f"  ✗ 第 1 条失败: {fmt_response(resp)}")
        print("    (实验 1 失败,可能是模板未审核 / 字段格式不对)")


# ============================================================
# 实验 2: 不重新授权,发第 2 条
# ============================================================


def exp2_no_reauth(openid: str) -> None:
    section("实验 2 / 不重新授权,发第 2 条 (期望: 失败)")
    wait_for_user(
        "不要重新触发 wx.requestSubscribeMessage,直接尝试发第 2 条。\n"
        "(如果 30 秒前刚授权过,grant 可能还在'窗口期',多等一会再继续)"
    )

    print("尝试发送第 2 条(无新授权)...")
    resp = try_send(openid, TEMPLATE_ID, "测试主播A-未重新授权")

    if resp.get("errcode") == 0:
        print("  ⚠️  第 2 条居然成功了?!")
        print("     这意味着:一次 accept 可用多次?")
        print("     记录到 reports/wechat_grant.md 实验 2 的'实际'列。")
    else:
        print(f"  ✓ 第 2 条失败,errcode={resp.get('errcode')}({explain_error(resp.get('errcode'))})")
        print("    grant 应该仍为 1,consumed 仍为 1")
        grant = state["grants"][TEMPLATE_ID]
        print(f"    当前 grant: granted={grant['granted_count']}, consumed={grant['consumed_count']}")


# ============================================================
# 实验 3: 重新授权,发第 3 条
# ============================================================


def exp3_reauth(openid: str) -> None:
    section("实验 3 / 重新授权,发第 3 条 (期望: 成功)")
    wait_for_user(
        "再次触发 wx.requestSubscribeMessage,让用户重新授权。"
    )

    increment_granted(TEMPLATE_ID, source="wx.requestSubscribeMessage.accept (再次)")
    print("  ✓ grant +1(再次 accept)")

    print("尝试发送第 3 条...")
    resp = try_send(openid, TEMPLATE_ID, "测试主播A-重新授权")

    if resp.get("errcode") == 0:
        increment_consumed(TEMPLATE_ID, resp)
        print("  ✓ 第 3 条发送成功")
    else:
        print(f"  ✗ 第 3 条失败: {fmt_response(resp)}")


# ============================================================
# 实验 4: "总是保持以上选择"
# ============================================================


def exp4_always_allow(openid: str) -> None:
    section("实验 4 / 用户勾选'总是保持以上选择' (期望: 行为待定)")
    print("微信小程序测试号可能没有'总是保持以上选择'选项。")
    print("如果有,执行以下操作后记录实际行为:")
    print("  - 在微信里: 设置 → 通知 → 找到测试号 → 开启'总是保持以上选择'")
    print("  - 然后连续发 3 条,看是否都需要重新授权")
    print()
    wait_for_user("完成上述操作后继续")

    for i in range(1, 4):
        print(f"  iter {i}: 发送 (无新授权)...")
        resp = try_send(openid, TEMPLATE_ID, f"总是保持-{i}")

        if resp.get("errcode") == 0:
            increment_consumed(TEMPLATE_ID, resp)
            # 注意:成功不代表有 grant,可能微信侧有'总是允许'特权
            print(f"     → 成功(无需新 grant?)")
        else:
            print(f"     → 失败: {fmt_response(resp)}")
            if i == 1:
                print("     → 即使勾选'总是保持'仍需每次授权?")
            break
        time.sleep(2)


# ============================================================
# 实验 5: 客户端伪造 accept
# ============================================================


def exp5_forged_accept(openid: str) -> None:
    section("实验 5 / 客户端伪造 accept (期望: 微信能识别 / 或不能)")
    print("场景模拟:恶意客户端或脚本,跳过 wx.requestSubscribeMessage,")
    print("直接调我们的 /api/v1/notifications/request-grant 声称 user 已 accept。")
    print("服务端 granted 会 +1(乐观记账),但实际微信侧没收到 user 的 accept。")
    print("此时直接调 send,微信会怎么响应?")

    increment_granted(TEMPLATE_ID, source="FORGED: skip wx.requestSubscribeMessage")
    print("  ⚠️  模拟服务端被骗: granted +1(实际微信侧没 accept)")

    print("尝试发送(无任何 wx.requestSubscribeMessage)...")
    resp = try_send(openid, TEMPLATE_ID, "伪造-无授权")

    if resp.get("errcode") == 0:
        print("  ⚠️  微信居然允许发送?!")
        print("     含义:微信**不验证**调用方是否真的拿到了 user 的 accept。")
        print("     后果:服务端无法独立验证 grant 真实性。")
        print("     我们的 grant 模型只能依靠客户端诚实 + 异常检测。")
        increment_consumed(TEMPLATE_ID, resp)
    elif resp.get("errcode") in (43101, 43102):
        print(f"  ✓ 微信返回 {resp.get('errcode')},识别为未授权")
        print("    但我们的 granted 已 +1,这是 server 端的偏差(乐观记账固有)")
    else:
        print(f"  ? 其他响应: {fmt_response(resp)}")


# ============================================================
# 实验 6: 用户拒收某模板
# ============================================================


def exp6_user_rejected(openid: str) -> None:
    section("实验 6 / 用户在微信侧拒收该模板 (期望: 43101)")
    print("在测试小程序里(或微信设置),找到订阅消息 → 关闭该模板。")
    print("然后尝试 send。")
    wait_for_user("完成上述操作后继续")

    print("尝试发送(用户已拒收)...")
    resp = try_send(openid, TEMPLATE_ID, "拒收测试")

    if resp.get("errcode") in (43101, 43102):
        print(f"  ✓ 微信返回 {resp.get('errcode')}({explain_error(resp.get('errcode'))})")
        print("    用户在微信侧拒收生效")
    elif resp.get("errcode") == 0:
        print("  ⚠️  即使在微信侧拒收,API 仍返回成功?")
        print("     需要去查用户微信 app 实际行为(推送是否真到?)")
    else:
        print(f"  ? 其他响应: {fmt_response(resp)}")


# ============================================================
# 主流程
# ============================================================


def main() -> None:
    section("Gate 0A / 微信通知真实性实验")
    print("验证 v0.2 grant 模型假设是否成立。")
    print("前置条件:")
    print("  - WECHAT-TEST-ACCOUNT.md §1-§3 已完成")
    print("  - experiments/.env 已配置 WX_APPID / WX_SECRET / WX_TEMPLATE_LIVE_START")
    print()
    print("本实验会跑 6 个场景,每个场景都需要你在手机上配合操作。")
    print("所有结果写入 data/grant_state.json。")
    print()

    openid = step0_login()

    exp1_first_send(openid)
    exp2_no_reauth(openid)
    exp3_reauth(openid)
    exp4_always_allow(openid)
    exp5_forged_accept(openid)
    exp6_user_rejected(openid)

    section("实验完成 / 汇总")
    print("grant 状态:")
    print(json.dumps(state["grants"], indent=2, ensure_ascii=False))
    print()
    print(f"详细日志: data/grant_state.json")
    print(f"事件总数: test_log={len(state.get('test_log', []))}")
    print()
    print("下一步:把结果填入 reports/wechat_grant.md")


if __name__ == "__main__":
    main()