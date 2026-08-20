"""Formal WeChat subscribe-message adapter for Gate 1.6-4.

Provider-specific template fields, access-token transport, and raw result codes
stay in infrastructure. The application layer sees only normalized outcomes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)

WX_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WX_SEND_SUBSCRIBE_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

ERR_OK = 0
ERR_USER_REFUSE = 43101
ERR_TEMPLATE_INVALID = 40037
ERR_RATE_LIMIT = 45009
ERR_TOKEN_INVALID = 40001
ERR_TOKEN_EXPIRED = 42001


@dataclass(frozen=True)
class WeChatRawResponse:
    http_status: int
    body: object


class WeChatTokenUnavailableError(RuntimeError):
    """Token acquisition failed before any message request could be issued."""


class WeChatSendAmbiguousError(RuntimeError):
    """Message request may have reached WeChat but no authoritative result exists."""


@runtime_checkable
class WeChatProviderGateway(Protocol):
    async def send(
        self,
        message: WeChatLiveStartMessage,
        data: dict[str, dict[str, str]],
    ) -> WeChatRawResponse: ...


def build_live_start_template_data(
    message: WeChatLiveStartMessage,
) -> dict[str, dict[str, str]]:
    """Translate semantic content into the accepted five-field template shape."""

    return {
        "thing1": {"value": message.anchor_name[:20]},
        "thing2": {"value": message.room_title[:20]},
        "time3": {"value": message.start_time},
        "thing5": {"value": (message.theme or "开播啦")[:20]},
        "thing6": {"value": (message.activity or "无")[:20]},
    }


def _message_from_body(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    value = body.get("errmsg")
    if value is None:
        return None
    return str(value)[:255]


def normalize_wechat_response(raw: WeChatRawResponse) -> ProviderOutcome:
    """Map only evidence-backed provider results; unknowns remain conservative."""

    if raw.http_status >= 500:
        return ProviderOutcome(
            ProviderOutcomeKind.RETRYABLE,
            GrantEffect.PRESERVE,
            provider_code=f"HTTP_{raw.http_status}",
            provider_message="wechat server unavailable",
        )
    if raw.http_status < 200 or raw.http_status >= 300:
        return ProviderOutcome(
            ProviderOutcomeKind.AMBIGUOUS,
            GrantEffect.PRESERVE,
            provider_code=f"HTTP_{raw.http_status}",
            provider_message="unexpected wechat http status",
        )
    if not isinstance(raw.body, dict):
        return ProviderOutcome(
            ProviderOutcomeKind.AMBIGUOUS,
            GrantEffect.PRESERVE,
            provider_code="MALFORMED_RESPONSE",
            provider_message="wechat response body is not an object",
        )

    raw_code = raw.body.get("errcode")
    try:
        code = int(raw_code)
    except (TypeError, ValueError):
        return ProviderOutcome(
            ProviderOutcomeKind.AMBIGUOUS,
            GrantEffect.PRESERVE,
            provider_code="MALFORMED_ERRCODE",
            provider_message=_message_from_body(raw.body),
        )

    message = _message_from_body(raw.body)
    code_text = str(code)
    if code == ERR_OK:
        return ProviderOutcome(
            ProviderOutcomeKind.ACCEPTED,
            GrantEffect.CONSUME,
            provider_code=code_text,
            provider_message=message,
        )
    if code == ERR_USER_REFUSE:
        return ProviderOutcome(
            ProviderOutcomeKind.AUTH_REQUIRED,
            GrantEffect.CONSUME,
            provider_code=code_text,
            provider_message=message,
        )
    if code == ERR_TEMPLATE_INVALID:
        return ProviderOutcome(
            ProviderOutcomeKind.CONFIG_BLOCKED,
            GrantEffect.PRESERVE,
            provider_code=code_text,
            provider_message=message,
        )
    if code in {ERR_RATE_LIMIT, ERR_TOKEN_INVALID, ERR_TOKEN_EXPIRED}:
        return ProviderOutcome(
            ProviderOutcomeKind.RETRYABLE,
            GrantEffect.PRESERVE,
            provider_code=code_text,
            provider_message=message,
        )

    # No evidence-backed semantics exist for arbitrary non-zero codes. Do not
    # silently turn them into retryable or terminal failures.
    return ProviderOutcome(
        ProviderOutcomeKind.AMBIGUOUS,
        GrantEffect.PRESERVE,
        provider_code=code_text,
        provider_message=message,
    )


class WeChatSubscribeFormalAdapter:
    """Application-owned provider contract implemented over an injected gateway."""

    def __init__(self, gateway: WeChatProviderGateway) -> None:
        if not isinstance(gateway, WeChatProviderGateway):
            raise TypeError("gateway must implement WeChatProviderGateway")
        self._gateway = gateway

    async def send(self, message: WeChatLiveStartMessage) -> ProviderOutcome:
        data = build_live_start_template_data(message)
        try:
            raw = await self._gateway.send(message, data)
        except WeChatTokenUnavailableError:
            return ProviderOutcome(
                ProviderOutcomeKind.RETRYABLE,
                GrantEffect.PRESERVE,
                provider_code="TOKEN_UNAVAILABLE",
                provider_message="wechat token unavailable",
            )
        except WeChatSendAmbiguousError:
            return ProviderOutcome(
                ProviderOutcomeKind.AMBIGUOUS,
                GrantEffect.PRESERVE,
                provider_code="SEND_TRANSPORT_AMBIGUOUS",
                provider_message="wechat send outcome ambiguous",
            )
        return normalize_wechat_response(raw)


class HttpxWeChatProviderGateway:
    """Async HTTP transport with private in-memory access-token cache.

    The caller owns the injected AsyncClient lifetime. Secrets/tokens are never
    returned through provider outcomes and this class performs no persistence.
    """

    def __init__(
        self,
        *,
        appid: str,
        app_secret: str,
        client: httpx.AsyncClient,
    ) -> None:
        if not appid.strip() or not app_secret.strip():
            raise ValueError("appid and app_secret are required")
        self._appid = appid
        self._app_secret = app_secret
        self._client = client
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def _get_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._access_token_expires_at - 300:
            return self._access_token
        try:
            response = await self._client.get(
                WX_TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": self._appid,
                    "secret": self._app_secret,
                },
            )
            body: Any = response.json()
        except (httpx.RequestError, ValueError) as exc:
            raise WeChatTokenUnavailableError("wechat token request failed") from exc

        if response.status_code >= 500:
            raise WeChatTokenUnavailableError("wechat token endpoint unavailable")
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise WeChatTokenUnavailableError("wechat token response rejected")

        token = body["access_token"]
        expires_in = body.get("expires_in", 7200)
        try:
            ttl = max(600, int(expires_in))
        except (TypeError, ValueError):
            ttl = 7200
        self._access_token = token
        self._access_token_expires_at = now + ttl
        return token

    async def send(
        self,
        message: WeChatLiveStartMessage,
        data: dict[str, dict[str, str]],
    ) -> WeChatRawResponse:
        token = await self._get_access_token()
        payload: dict[str, object] = {
            "touser": message.openid,
            "template_id": message.template_id,
            "data": data,
            "miniprogram_state": message.miniprogram_state,
        }
        if message.page is not None:
            payload["page"] = message.page

        try:
            response = await self._client.post(
                WX_SEND_SUBSCRIBE_URL,
                params={"access_token": token},
                json=payload,
            )
            try:
                body: object = response.json()
            except ValueError:
                body = None
        except httpx.RequestError as exc:
            # Once POST is attempted, transport failure cannot prove whether the
            # provider accepted the message. Preserve ambiguity, never blind retry.
            raise WeChatSendAmbiguousError("wechat send response unavailable") from exc

        if isinstance(body, dict):
            try:
                code = int(body.get("errcode"))
            except (TypeError, ValueError):
                code = None
            if code in {ERR_TOKEN_INVALID, ERR_TOKEN_EXPIRED}:
                # The explicit response proves this token was rejected; invalidate
                # cache so a later scheduled retry obtains a fresh token.
                self._access_token = None
                self._access_token_expires_at = 0.0
        return WeChatRawResponse(response.status_code, body)
