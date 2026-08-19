"""Formal Douyin adapter for Gate 1.3-3.

The adapter consumes provider-side records through an injected gateway and
normalizes them into the application-owned LivePlatformAdapter contract. It does
not import the legacy top-level platform_adapters package or Gate 0 experiments.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from stage_letter.application.platforms import (
    CreatorProfileSnapshot,
    LiveSnapshot,
    ResolvedCreator,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus

from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_exception,
    normalize_explicit_status,
    unknown_snapshot_for_failure,
)


DOUYIN_PLATFORM = "douyin"
DOUYIN_LIVE_VALUES = frozenset({2})
DOUYIN_OFFLINE_VALUES = frozenset({4})


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class DouyinIdentityRecord:
    """Provider-side stable Douyin identity returned by the transport gateway."""

    sec_uid: str
    display_name: str | None = None
    room_id: str | None = None
    canonical_url: str | None = None

    def __post_init__(self) -> None:
        _required(self.sec_uid, "sec_uid")


@dataclass(frozen=True)
class DouyinProfileRecord:
    sec_uid: str
    observed_at: datetime
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None

    def __post_init__(self) -> None:
        _required(self.sec_uid, "sec_uid")


@dataclass(frozen=True)
class DouyinLiveRecord:
    """Successfully parsed provider record before formal live-state normalization."""

    sec_uid: str
    observed_at: datetime
    raw_status: object
    source: str
    room_id: str | None = None
    title: str | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.sec_uid, "sec_uid")
        _required(self.source, "source")


@runtime_checkable
class DouyinProviderGateway(Protocol):
    """Provider transport seam.

    Concrete transport code may use StreamGet or another evidence-backed source,
    but must normalize request/parse/auth failures into ProviderOperationError.
    """

    async def resolve_identity(self, input: str) -> DouyinIdentityRecord: ...

    async def fetch_profile(self, sec_uid: str) -> DouyinProfileRecord: ...

    async def fetch_live(self, sec_uid: str) -> DouyinLiveRecord: ...


class DouyinFormalAdapter:
    """Formal Douyin implementation of the LivePlatformAdapter contract."""

    platform = DOUYIN_PLATFORM

    def __init__(self, gateway: DouyinProviderGateway) -> None:
        if not isinstance(gateway, DouyinProviderGateway):
            raise TypeError("gateway must implement DouyinProviderGateway")
        self._gateway = gateway

    @staticmethod
    def _require_account(account: PlatformAccount) -> None:
        if account.platform != DOUYIN_PLATFORM:
            raise ValueError(f"expected douyin account, got {account.platform!r}")

    @staticmethod
    def _identity_failure(*, source: str, detail: str) -> ProviderOperationError:
        return ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.AMBIGUOUS,
                source=source,
                detail=detail,
            )
        )

    async def resolve_creator(self, input: str) -> ResolvedCreator:
        record = await self._gateway.resolve_identity(input)
        return ResolvedCreator(
            platform=DOUYIN_PLATFORM,
            platform_user_id=record.sec_uid,
            display_name=record.display_name,
            room_id=record.room_id,
            canonical_url=record.canonical_url,
        )

    async def get_creator_profile(
        self,
        account: PlatformAccount,
    ) -> CreatorProfileSnapshot:
        self._require_account(account)
        record = await self._gateway.fetch_profile(account.platform_user_id)
        if record.sec_uid != account.platform_user_id:
            raise self._identity_failure(
                source="douyin.profile",
                detail="provider identity mismatch",
            )
        return CreatorProfileSnapshot(
            platform=DOUYIN_PLATFORM,
            platform_user_id=record.sec_uid,
            observed_at=record.observed_at,
            display_name=record.display_name,
            avatar_url=record.avatar_url,
            bio=record.bio,
        )

    async def get_live_snapshot(self, account: PlatformAccount) -> LiveSnapshot:
        self._require_account(account)
        try:
            record = await self._gateway.fetch_live(account.platform_user_id)
        except ProviderOperationError as exc:
            return unknown_snapshot_for_failure(
                account,
                observed_at=datetime.now().astimezone(),
                failure=exc.failure,
            )
        except (TimeoutError, ConnectionError) as exc:
            failure = classify_exception(exc, source="douyin.live")
            return unknown_snapshot_for_failure(
                account,
                observed_at=datetime.now().astimezone(),
                failure=failure,
            )

        if record.sec_uid != account.platform_user_id:
            failure = ProviderFailure(
                kind=ProviderFailureKind.AMBIGUOUS,
                source=record.source,
                detail="provider identity mismatch",
            )
            return unknown_snapshot_for_failure(
                account,
                observed_at=record.observed_at,
                failure=failure,
            )

        status = normalize_explicit_status(
            record.raw_status,
            live_values=DOUYIN_LIVE_VALUES,
            offline_values=DOUYIN_OFFLINE_VALUES,
        )

        # Gate 0A evidence established that historical room metadata/title may be
        # stale while explicit status=4 is OFFLINE. Metadata never overrides the
        # explicit status. A start time is accepted only for explicit LIVE.
        return LiveSnapshot(
            platform=DOUYIN_PLATFORM,
            platform_user_id=record.sec_uid,
            status=status,
            observed_at=record.observed_at,
            source=record.source,
            source_started_at=(record.source_started_at if status is LiveStatus.LIVE else None),
            room_id=record.room_id,
            canonical_url=account.canonical_url,
            title=record.title,
        )
