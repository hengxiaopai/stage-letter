"""微信开放 API 客户端 + grant 状态管理(共享工具)。

提供给 wechat_grant_demo.py 与 wechat_trust_test.py 共用。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


# ============================================================
# 路径与常量
# ============================================================

EXPERIMENTS_DIR = Path(__file__).parent
DATA_DIR = EXPERIMENTS_DIR / "data"
STATE_FILE = DATA_DIR / "grant_state.json"

# 微信 API 基础地址
WX_API_BASE = "https://api.weixin.qq.com"
WX_CODE2SESSION_URL = f"{WX_API_BASE}/sns/jscode2session"
WX_TOKEN_URL = f"{WX_API_BASE}/cgi-bin/token"
WX_SEND_SUBSCRIBE_URL = f"{WX_API_BASE}/cgi-bin/message/subscribe/send"

# 微信错误码参考
WX_ERROR_CODES = {
    0: "成功",
    40001: "AppSecret 错误 / access_token 失效",
    40003: "openid 错误",
    40037: "模板 ID 不存在",
    41004: "appid 缺失",
    41008: "缺少 openid",
    42001: "access_token 超时",
    43004: "需要接收者关注",
    43101: "用户拒绝接受 / 已退订",
    43102: "用户未订阅该消息",
    44002: "POST 数据为空",
    45009: "调用频率超过限制",
    47003: "参数错误",
}


# ============================================================
# 配置加载
# ============================================================


def load_env() -> dict[str, str]:
    """从 .env 文件加载配置(简单 key=value 解析,无引号转义)。"""
    env_file = EXPERIMENTS_DIR / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    # 环境变量覆盖文件
    for k in ("WX_APPID", "WX_SECRET", "WX_TEMPLATE_LIVE_START"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


# ============================================================
# 状态管理(JSON 文件,模拟 production DB)
# ============================================================


def default_state() -> dict:
    return {
        "user": {},
        "grants": {},  # template_id -> { granted_count, consumed_count, history }
        "test_log": [],
        "trust_test_log": [],
        "access_token_cache": {},
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return default_state()
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_state()


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def record_event(state: dict, log_key: str, event_type: str, **data) -> None:
    """记录一条事件到 state 并落盘。"""
    state.setdefault(log_key, []).append(
        {
            "timestamp": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event_type,
            **data,
        }
    )
    save_state(state)


# ============================================================
# 微信 API 客户端
# ============================================================


class WeChatError(Exception):
    """微信 API 返回非 0 errcode 时抛出。"""

    def __init__(self, errcode: int, errmsg: str, full_response: dict | None = None):
        self.errcode = errcode
        self.errmsg = errmsg
        self.full_response = full_response or {}
        super().__init__(f"WeChat API error {errcode}: {errmsg}")


class WeChatClient:
    """微信开放 API 简易封装。"""

    def __init__(self, appid: str, secret: str):
        if not appid or not secret:
            raise ValueError("appid 和 secret 必须提供")
        self.appid = appid
        self.secret = secret
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    def get_access_token(self, force_refresh: bool = False) -> str:
        """获取 access_token(带内存缓存,过期前 5 分钟自动刷新)。"""
        now = time.time()
        if (
            not force_refresh
            and self._access_token
            and now < self._access_token_expires_at - 300
        ):
            return self._access_token

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                WX_TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": self.appid,
                    "secret": self.secret,
                },
            )
            data = resp.json()

        if "access_token" not in data:
            raise WeChatError(
                errcode=data.get("errcode", -1),
                errmsg=data.get("errmsg", "unknown"),
                full_response=data,
            )

        self._access_token = data["access_token"]
        self._access_token_expires_at = now + int(data.get("expires_in", 7200))
        return self._access_token

    def code2session(self, code: str) -> dict:
        """用 wx.login 拿到的 code 换 openid / session_key。"""
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                WX_CODE2SESSION_URL,
                params={
                    "appid": self.appid,
                    "secret": self.secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()

        if "openid" not in data:
            raise WeChatError(
                errcode=data.get("errcode", -1),
                errmsg=data.get("errmsg", "unknown"),
                full_response=data,
            )
        return data

    def send_subscribe_message(
        self,
        openid: str,
        template_id: str,
        data: dict,
        page: str | None = None,
        miniprogram_state: str = "developer",
    ) -> dict:
        """发送一次订阅消息。

        返回微信原始响应 dict:
          { errcode: 0, errmsg: "ok" }   成功
          { errcode: 43101, errmsg: ... } 用户拒收
          ...

        注意:此方法**不抛异常**,返回原始响应让 caller 决定如何处理。
        """
        token = self.get_access_token()
        payload = {
            "touser": openid,
            "template_id": template_id,
            "data": data,
            "miniprogram_state": miniprogram_state,
        }
        if page:
            payload["page"] = page

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                WX_SEND_SUBSCRIBE_URL,
                params={"access_token": token},
                json=payload,
            )
            return resp.json()


# ============================================================
# 输出辅助
# ============================================================


def section(title: str) -> None:
    """打印分隔小节标题。"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def wait_for_user(prompt: str) -> None:
    """提示用户做某事,按回车继续。"""
    print(f"\n>>> {prompt}")
    try:
        input("按回车继续...")
    except EOFError:
        pass


def explain_error(errcode: int) -> str:
    """把微信错误码翻译成人话。"""
    return WX_ERROR_CODES.get(errcode, f"未知错误({errcode})")