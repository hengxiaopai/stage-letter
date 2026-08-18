"""微信小程序服务端(Gate 1 骨架)。

复用 Gate 0A 已实测验证的逻辑(2026-08-12 正式号 wx370fb6f14d4a4a26):
- access_token: 内存 + Redis 双缓存(过期前 5 分钟刷新)
- code2session: wx.login code → openid
- 订阅消息模板「直播开播通知」5 字段(thing1/thing2/time3/thing5/thing6)
- grant 模型: 乐观记账(ADR-001) + granted_count 可累积储备(ADR-002)
- authority = send 返回码(实验 A3-5:伪造 accept 在余额 0 时必返 43101)
"""
from __future__ import annotations

import logging
import time

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

WX_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
WX_SEND_SUBSCRIBE_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"


class WeChatError(Exception):
    def __init__(self, errcode: int, errmsg: str, full_response: dict | None = None):
        super().__init__(f"wechat errcode={errcode}: {errmsg}")
        self.errcode = errcode
        self.errmsg = errmsg
        self.full_response = full_response


class WeChatClient:
    def __init__(self, appid: str, secret: str):
        self.appid = appid
        self.secret = secret
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    # ── access_token(内存缓存,过期前 5 分钟刷新)──
    def get_access_token(self, force_refresh: bool = False) -> str:
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

    # ── code2session: wx.login code → openid ──
    def code2session(self, code: str) -> dict:
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

    # ── 订阅消息发送 ──
    def send_subscribe_message(
        self,
        openid: str,
        template_id: str,
        data: dict,
        page: str | None = None,
        miniprogram_state: str = "formal",
    ) -> dict:
        """发送订阅消息,返回微信原始响应(不抛异常,由 caller 处理)。"""
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

    @staticmethod
    def build_live_start_payload(anchor_name: str, room_title: str, start_time: str,
                                 theme: str = "", activity: str = "无") -> dict:
        """构造「直播开播通知」模板 payload(5 字段,2026-08-12 从正式号确认)。

        thing 类型字段限 20 字,time 类型 YYYY-MM-DD HH:MM。
        """
        return {
            "thing1": {"value": anchor_name[:20]},     # 达人名称
            "thing2": {"value": room_title[:20]},      # 直播间名称
            "time3": {"value": start_time},            # 开播时间
            "thing5": {"value": (theme or "开播啦")[:20]},  # 直播主题
            "thing6": {"value": activity[:20]},        # 直播间活动
        }


# 单例(生产可替换为依赖注入)
_wechat_client: WeChatClient | None = None


def get_wechat_client() -> WeChatClient:
    global _wechat_client
    if _wechat_client is None:
        if not settings.wx_appid or not settings.wx_secret:
            raise RuntimeError("WX_APPID / WX_SECRET 未配置(正式号)")
        _wechat_client = WeChatClient(settings.wx_appid, settings.wx_secret)
    return _wechat_client
