"""Formal notification provider infrastructure."""

from .wechat import (
    ERR_RATE_LIMIT,
    ERR_TEMPLATE_INVALID,
    ERR_TOKEN_EXPIRED,
    ERR_TOKEN_INVALID,
    ERR_USER_REFUSE,
    HttpxWeChatProviderGateway,
    WeChatProviderGateway,
    WeChatRawResponse,
    WeChatSendAmbiguousError,
    WeChatSubscribeFormalAdapter,
    WeChatTokenUnavailableError,
    build_live_start_template_data,
    normalize_wechat_response,
)

__all__ = [
    "ERR_RATE_LIMIT",
    "ERR_TEMPLATE_INVALID",
    "ERR_TOKEN_EXPIRED",
    "ERR_TOKEN_INVALID",
    "ERR_USER_REFUSE",
    "HttpxWeChatProviderGateway",
    "WeChatProviderGateway",
    "WeChatRawResponse",
    "WeChatSendAmbiguousError",
    "WeChatSubscribeFormalAdapter",
    "WeChatTokenUnavailableError",
    "build_live_start_template_data",
    "normalize_wechat_response",
]
