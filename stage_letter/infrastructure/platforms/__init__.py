"""Formal platform adapter infrastructure for Stage Letter."""

from .bilibili import BilibiliFormalAdapter
from .bilibili_http import BilibiliHttpGateway
from .douyin import DouyinFormalAdapter
from .douyin_streamget import STREAMGET_DOUYIN_SOURCE, StreamGetDouyinGateway
from .douyu import DouyuFormalAdapter
from .douyu_http import DouyuHttpGateway
from .factory import FORMAL_PLATFORMS, build_formal_adapter_registry
from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_exception,
    classify_http_failure,
    normalize_explicit_status,
    unknown_snapshot_for_failure,
)
from .huya import HuyaFormalAdapter
from .huya_http import HuyaHttpGateway
from .registry import AdapterNotFoundError, AdapterRegistry

__all__ = [
    "AdapterNotFoundError",
    "AdapterRegistry",
    "BilibiliFormalAdapter",
    "BilibiliHttpGateway",
    "DouyinFormalAdapter",
    "DouyuFormalAdapter",
    "DouyuHttpGateway",
    "FORMAL_PLATFORMS",
    "HuyaFormalAdapter",
    "HuyaHttpGateway",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderOperationError",
    "STREAMGET_DOUYIN_SOURCE",
    "StreamGetDouyinGateway",
    "build_formal_adapter_registry",
    "classify_exception",
    "classify_http_failure",
    "normalize_explicit_status",
    "unknown_snapshot_for_failure",
]
