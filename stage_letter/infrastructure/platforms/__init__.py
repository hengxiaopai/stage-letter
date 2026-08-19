"""Formal platform adapter infrastructure for Stage Letter."""

from .douyin_streamget import STREAMGET_DOUYIN_SOURCE, StreamGetDouyinGateway
from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_exception,
    classify_http_failure,
    normalize_explicit_status,
    unknown_snapshot_for_failure,
)
from .registry import AdapterNotFoundError, AdapterRegistry

__all__ = [
    "AdapterNotFoundError",
    "AdapterRegistry",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderOperationError",
    "STREAMGET_DOUYIN_SOURCE",
    "StreamGetDouyinGateway",
    "classify_exception",
    "classify_http_failure",
    "normalize_explicit_status",
    "unknown_snapshot_for_failure",
]
