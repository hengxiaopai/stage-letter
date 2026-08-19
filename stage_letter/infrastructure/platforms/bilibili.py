"""Formal Bilibili adapter for Gate 1.3-4A.

Only evidence-backed Bilibili live_status semantics are normalized here. Provider
transport is injected through BilibiliProviderGateway; this module does not import
the legacy top-level platform_adapters package.
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


BILIBILI_PLATFORM = "bilibili"
# Stage Letter's canonical LIVE means the creator is actually broadcasting now.
# Bilibili raw status 2 is carousel/replay activity, so it must not trigger a
# live-start truth/event for the creator.
BILIBILI_LIVE_VALUES = frozenset({1})
BILIBILI_OFFLINE_VALUES = frozenset({0, 2})


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class BilibiliIdentityRecord:
    """Provider-side stable Bilibili identity.

    uid is the canonical PlatformAccount identity. room_id is navigation/live-room
    metadata and may change independently.
    """

    uid: str
    display_name: str | None = None
    room_id: str | None = None
    canonical_url: str | None = None

    def __post_init__(self) -> None:
        _required(self.uid, "uid")


@dataclass(frozen=True)
class BilibiliProfileRecord:
    uid: str
    observed_at: datetime
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None

    def __post_init__(self) -> None:
        _required(self.uid, "uid")


@dataclass(frozen=True)
class BilibiliLiveRecord:
    uid: str
    observed_at: datetime
    raw_live_status: object
    source: str
    room_id: str | None = None
    title: str | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.uid, "uid")
        _required(self.source, "source")


@runtime_checkable
class BilibiliProviderGateway(Protocol):
    async def resolve_identity(self, input: str) -> BilibiliIdentityRecord: ...

    async def fetch_profile(self, uid: str) -> BilibiliProfileRecord: ...

    async def fetch_live(self, uid: str) -> BilibiliLiveRecord: ...


class BilibiliFormalAdapter:
    platform = BILIBILI_PLATFORM

    def __init__(self, gateway: BilibiliProviderGateway) -> None:
        if not isinstance(gateway, BilibiliProviderGateway):
            raise TypeError("gateway must implement BilibiliProviderGateway")
        self._gateway = gateway

    @staticmethod
    def _require_account(account: PlatformAccount) -> None:
        if account.platform != BILIBILI_PLATFORM:
            raise ValueError(f"expected bilibili account, got {account.platform!r}")

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
            platform=BILIBILI_PLATFORM,
            platform_user_id=record.uid,
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
        if record.uid != account.platform_user_id:
            raise self._identity_failure(
                source="bilibili.profile",
                detail="provider identity mismatch",
            )
        return CreatorProfileSnapshot(
            platform=BILIBILI_PLATFORM,
            platform_user_id=record.uid,
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
            failure = classify_exception(exc, source="bilibili.live")
            return unknown_snapshot_for_failure(
                account,
                observed_at=datetime.now().astimezone(),
                failure=failure,
            )

        if record.uid != account.platform_user_id:
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

        # bool is a subclass of int in Python. Treat it as provider type drift
        # rather than accidentally accepting True as 1 or False as 0.
        if isinstance(record.raw_live_status, bool):
            status = LiveStatus.UNKNOWN
        else:
            status = normalize_explicit_status(
                record.raw_live_status,
                live_values=BILIBILI_LIVE_VALUES,
                offline_values=BILIBILI_OFFLINE_VALUES,
            )

        return LiveSnapshot(
            platform=BILIBILI_PLATFORM,
            platform_user_id=record.uid,
            status=status,
            observed_at=record.observed_at,
            source=record.source,
            source_started_at=(record.source_started_at if status is LiveStatus.LIVE else None),
            room_id=record.room_id,
            canonical_url=account.canonical_url,
            title=record.title,
        )
