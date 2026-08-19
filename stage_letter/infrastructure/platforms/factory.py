"""Formal cross-platform adapter composition for Gate 1.3-4D.

This module wires only Stage Letter's formal provider implementations into the
infrastructure-owned AdapterRegistry. Construction performs no provider request;
network access remains inside the concrete gateways when an adapter operation is
actually invoked.
"""
from __future__ import annotations

from .bilibili import BILIBILI_PLATFORM, BilibiliFormalAdapter
from .bilibili_http import BilibiliHttpGateway
from .douyin import DOUYIN_PLATFORM, DouyinFormalAdapter
from .douyin_streamget import StreamGetDouyinGateway
from .douyu import DOUYU_PLATFORM, DouyuFormalAdapter
from .douyu_http import DouyuHttpGateway
from .huya import HUYA_PLATFORM, HuyaFormalAdapter
from .huya_http import HuyaHttpGateway
from .registry import AdapterRegistry


FORMAL_PLATFORMS = (
    BILIBILI_PLATFORM,
    DOUYIN_PLATFORM,
    DOUYU_PLATFORM,
    HUYA_PLATFORM,
)


def build_formal_adapter_registry(
    *,
    douyin_cookie: str | None = None,
) -> AdapterRegistry:
    """Build a fresh explicit registry for all currently formalized platforms.

    StreamGet remains lazily imported by StreamGetDouyinGateway, so constructing
    this registry does not require the optional Douyin provider runtime to be
    importable and does not perform provider I/O.
    """

    registry = AdapterRegistry()
    registry.register(
        DOUYIN_PLATFORM,
        DouyinFormalAdapter(StreamGetDouyinGateway(cookie=douyin_cookie)),
    )
    registry.register(
        BILIBILI_PLATFORM,
        BilibiliFormalAdapter(BilibiliHttpGateway()),
    )
    registry.register(
        HUYA_PLATFORM,
        HuyaFormalAdapter(HuyaHttpGateway()),
    )
    registry.register(
        DOUYU_PLATFORM,
        DouyuFormalAdapter(DouyuHttpGateway()),
    )
    return registry
