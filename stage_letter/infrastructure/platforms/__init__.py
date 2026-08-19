"""Formal platform adapter infrastructure for Stage Letter."""

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
    "classify_exception",
    "classify_http_failure",
    "normalize_explicit_status",
    "unknown_snapshot_for_failure",
]
