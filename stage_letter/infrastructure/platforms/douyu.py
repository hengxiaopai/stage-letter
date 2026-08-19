"""Formal Douyu adapter for Gate 1.3-4C.

Only evidence-backed Douyu creator-live semantics are normalized here. Provider
transport is injected through DouyuProviderGateway; this module never imports the
legacy top-level platform_adapters package.
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


DOUYU_PLATFORM = "douyu"
DOUYU_LIVE_VALUES = frozenset({1})
DOUYU_OFFLINE_VALUES = frozenset({2})


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class DouyuIdentityRecord:
    """Provider-side Douyu identity.

    Current evidence exposes room_id as the stable monitor key available to Stage
    Letter. No unproven creator uid is fabricated inward.
    """

    room_id: str
    display_name: str | None = None
    canonical_url: str | None = None

    def __post_init__(self) -> None:
        _required(self.room_id, "room_id")


@dataclass(frozen=True)
class DouyuProfileRecord:
    room_id: str
    observed_at: datetime
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None

    def __post_init__(self) -> None:
        _required(self.room_id, "room_id")


@dataclass(frozen=True)
class DouyuLiveRecord:
    room_id: str
    observed_at: datetime
    raw_live_status: object
    source: str
    title: str | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.room_id, "room_id")
        _required(self.source, "source")


@runtime_checkable
class DouyuProviderGateway(Protocol):
    async def resolve_identity(self, input: str) -> DouyuIdentityRecord: ...

    async def fetch_profile(self, room_id: str) -> DouyuProfileRecord: ...

    async def fetch_live(self, room_id: str) -> DouyuLiveRecord: ...


class DouyuFormalAdapter:
    platform = DOUYU_PLATFORM

    def __init__(self, gateway: DouyuProviderGateway) -> None:
        if not isinstance(gateway, DouyuProviderGateway):
            raise TypeError("gateway must implement DouyuProviderGateway")
        self._gateway = gateway

    @staticmethod
    def _require_account(account: PlatformAccount) -> None:
        if account.platform != DOUYU_PLATFORM:
            raise ValueError(f"expected douyu account, got {account.platform!r}")

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
            platform=DOUYU_PLATFORM,
            platform_user_id=record.room_id,
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
        if record.room_id != account.platform_user_id:
            raise self._identity_failure(
                source="douyu.profile",
                detail="provider identity mismatch",
            )
        return CreatorProfileSnapshot(
            platform=DOUYU_PLATFORM,
            platform_user_id=record.room_id,
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
            failure = classify_exception(exc, source="douyu.live")
            return unknown_snapshot_for_failure(
                account,
                observed_at=datetime.now().astimezone(),
                failure=failure,
            )

        if record.room_id != account.platform_user_id:
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

        # bool is an int subclass in Python and string lookalikes are provider
        # type drift. Only explicit integer show_status 1/2 is decisive.
        if isinstance(record.raw_live_status, bool):
            status = LiveStatus.UNKNOWN
        else:
            status = normalize_explicit_status(
                record.raw_live_status,
                live_values=DOUYU_LIVE_VALUES,
                offline_values=DOUYU_OFFLINE_VALUES,
            )

        return LiveSnapshot(
            platform=DOUYU_PLATFORM,
            platform_user_id=record.room_id,
            status=status,
            observed_at=record.observed_at,
            source=record.source,
            source_started_at=(record.source_started_at if status is LiveStatus.LIVE else None),
            room_id=record.room_id,
            canonical_url=account.canonical_url,
            title=record.title,
        )
