"""Provider-failure normalization for the formal Gate 1.3 adapter boundary.

This module converts transport/provider failure evidence into conservative formal
facts. It never upgrades failure/ambiguity into OFFLINE. Only an explicit,
provider-specific positive mapping may produce LIVE or OFFLINE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Collection

from stage_letter.application.platforms import LiveSnapshot
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus


class ProviderFailureKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    PARSE_ERROR = "PARSE_ERROR"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderFailure:
    """Provider/transport diagnostic evidence, never canonical live truth."""

    kind: ProviderFailureKind
    source: str
    http_status: int | None = None
    provider_code: str | int | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("source is required")


class ProviderOperationError(RuntimeError):
    """Explicit provider failure for operations that cannot return a snapshot."""

    def __init__(self, failure: ProviderFailure) -> None:
        self.failure = failure
        super().__init__(f"{failure.kind.value} from {failure.source}")


def classify_http_failure(
    status_code: int,
    *,
    source: str,
    provider_code: str | int | None = None,
    detail: str | None = None,
) -> ProviderFailure:
    """Classify HTTP evidence without making live-state claims."""

    if status_code == 401:
        kind = ProviderFailureKind.AUTH_REQUIRED
    elif status_code == 403:
        kind = ProviderFailureKind.FORBIDDEN
    elif status_code == 404:
        kind = ProviderFailureKind.NOT_FOUND
    elif status_code == 429:
        kind = ProviderFailureKind.RATE_LIMITED
    elif 500 <= status_code <= 599:
        kind = ProviderFailureKind.UPSTREAM_ERROR
    else:
        kind = ProviderFailureKind.UNKNOWN
    return ProviderFailure(
        kind=kind,
        source=source,
        http_status=status_code,
        provider_code=provider_code,
        detail=detail,
    )


def classify_exception(exc: BaseException, *, source: str) -> ProviderFailure:
    """Classify only evidence that is safe to infer from Python exception type."""

    if isinstance(exc, TimeoutError):
        kind = ProviderFailureKind.TIMEOUT
    elif isinstance(exc, ConnectionError):
        kind = ProviderFailureKind.NETWORK
    else:
        kind = ProviderFailureKind.UNKNOWN
    return ProviderFailure(kind=kind, source=source, detail=type(exc).__name__)


def unknown_snapshot_for_failure(
    account: PlatformAccount,
    *,
    observed_at: datetime,
    failure: ProviderFailure,
) -> LiveSnapshot:
    """Convert any provider failure/ambiguity into UNKNOWN, never OFFLINE."""

    return LiveSnapshot(
        platform=account.platform,
        platform_user_id=account.platform_user_id,
        status=LiveStatus.UNKNOWN,
        observed_at=observed_at,
        source=failure.source,
        source_started_at=None,
        room_id=account.room_id,
        canonical_url=account.canonical_url,
        title=None,
    )


def normalize_explicit_status(
    raw_status: object,
    *,
    live_values: Collection[object],
    offline_values: Collection[object],
) -> LiveStatus:
    """Map only explicit provider values; unknown/ambiguous values stay UNKNOWN."""

    if any(value in offline_values for value in live_values):
        raise ValueError("live_values and offline_values must be disjoint")
    if raw_status in live_values:
        return LiveStatus.LIVE
    if raw_status in offline_values:
        return LiveStatus.OFFLINE
    return LiveStatus.UNKNOWN
