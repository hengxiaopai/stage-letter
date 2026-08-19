"""Evidence-backed StreamGet transport for the formal Douyin adapter.

This module is the concrete provider gateway for Gate 1.3-3. It intentionally
uses stable Douyin profile/sec_uid identity and keeps StreamGet as an outer
infrastructure dependency. It never imports legacy platform_adapters or Gate 0
experiments.

Gate 0A evidence authorizes only the following live-state interpretation in the
formal adapter above this gateway:

    raw status 2 -> LIVE
    raw status 4 -> OFFLINE
    anything else / failure -> UNKNOWN

This gateway therefore returns raw provider status and metadata only. It does not
itself decide canonical live truth.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Protocol, runtime_checkable

from .douyin import (
    DouyinIdentityRecord,
    DouyinLiveRecord,
    DouyinProfileRecord,
)
from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_exception,
)


STREAMGET_DOUYIN_SOURCE = "streamget.profile"
_PROFILE_RE = re.compile(
    r"^https?://(?:www\.)?douyin\.com/user/([A-Za-z0-9._~-]{4,300})(?:[/?#].*)?$",
    re.IGNORECASE,
)
_SEC_UID_RE = re.compile(r"^[A-Za-z0-9._~-]{4,300}$")


@runtime_checkable
class StreamGetDouyinClient(Protocol):
    async def fetch_app_stream_data(self, url: str) -> dict[str, object]: ...


ClientFactory = Callable[[str | None], StreamGetDouyinClient]
Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_client_factory(cookie: str | None) -> StreamGetDouyinClient:
    # Deliberately lazy: importing the formal platform package must not require
    # StreamGet to be installed. Only an actual provider call loads it.
    try:
        from streamget import DouyinLiveStream
    except Exception as exc:  # pragma: no cover - exercised by real probe env
        raise ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.UNKNOWN,
                source=STREAMGET_DOUYIN_SOURCE,
                detail=f"streamget unavailable: {type(exc).__name__}",
            )
        ) from exc
    return DouyinLiveStream(cookies=cookie or None)


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_started_at(value: object) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class StreamGetDouyinGateway:
    """Concrete DouyinProviderGateway backed by StreamGet PROFILE/sec_uid reads."""

    def __init__(
        self,
        *,
        cookie: str | None = None,
        client_factory: ClientFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._cookie = cookie.strip() if cookie and cookie.strip() else None
        self._client_factory = client_factory or _default_client_factory
        self._clock = clock or _default_clock

    @staticmethod
    def canonical_profile_url(sec_uid: str) -> str:
        sec_uid = sec_uid.strip()
        if not _SEC_UID_RE.fullmatch(sec_uid):
            raise ProviderOperationError(
                ProviderFailure(
                    kind=ProviderFailureKind.UNKNOWN,
                    source=STREAMGET_DOUYIN_SOURCE,
                    detail="invalid sec_uid/profile identity",
                )
            )
        return f"https://www.douyin.com/user/{sec_uid}"

    @staticmethod
    def parse_sec_uid(value: str) -> str:
        text = value.strip()
        match = _PROFILE_RE.fullmatch(text)
        if match:
            return match.group(1)
        if _SEC_UID_RE.fullmatch(text):
            return text
        raise ProviderOperationError(
            ProviderFailure(
                kind=ProviderFailureKind.UNKNOWN,
                source=STREAMGET_DOUYIN_SOURCE,
                detail="input is not a stable Douyin profile/sec_uid identity",
            )
        )

    def _client(self) -> StreamGetDouyinClient:
        try:
            return self._client_factory(self._cookie)
        except ProviderOperationError:
            raise
        except Exception as exc:
            failure = classify_exception(exc, source=STREAMGET_DOUYIN_SOURCE)
            raise ProviderOperationError(failure) from exc

    @staticmethod
    def _assert_response_identity(room: dict[str, object], sec_uid: str) -> None:
        candidates: list[object] = [room.get("sec_uid"), room.get("anchor_sec_uid")]
        owner = room.get("owner")
        if isinstance(owner, dict):
            candidates.append(owner.get("sec_uid"))
        user = room.get("user")
        if isinstance(user, dict):
            candidates.append(user.get("sec_uid"))

        explicit = {_clean_optional(value) for value in candidates}
        explicit.discard(None)
        if explicit and explicit != {sec_uid}:
            raise ProviderOperationError(
                ProviderFailure(
                    kind=ProviderFailureKind.AMBIGUOUS,
                    source=STREAMGET_DOUYIN_SOURCE,
                    detail="StreamGet response identity mismatch",
                )
            )

    async def _fetch_room(self, sec_uid: str) -> dict[str, object]:
        profile_url = self.canonical_profile_url(sec_uid)
        client = self._client()
        try:
            room = await client.fetch_app_stream_data(profile_url)
        except ProviderOperationError:
            raise
        except Exception as exc:
            failure = classify_exception(exc, source=STREAMGET_DOUYIN_SOURCE)
            raise ProviderOperationError(failure) from exc

        if not isinstance(room, dict):
            raise ProviderOperationError(
                ProviderFailure(
                    kind=ProviderFailureKind.SCHEMA_DRIFT,
                    source=STREAMGET_DOUYIN_SOURCE,
                    detail="StreamGet returned non-dict room payload",
                )
            )
        self._assert_response_identity(room, sec_uid)
        return room

    async def resolve_identity(self, input: str) -> DouyinIdentityRecord:
        sec_uid = self.parse_sec_uid(input)
        room = await self._fetch_room(sec_uid)
        return DouyinIdentityRecord(
            sec_uid=sec_uid,
            display_name=_clean_optional(room.get("anchor_name")),
            room_id=_clean_optional(room.get("id") or room.get("room_id")),
            canonical_url=self.canonical_profile_url(sec_uid),
        )

    async def fetch_profile(self, sec_uid: str) -> DouyinProfileRecord:
        room = await self._fetch_room(sec_uid)
        return DouyinProfileRecord(
            sec_uid=sec_uid,
            observed_at=self._clock(),
            display_name=_clean_optional(room.get("anchor_name")),
            avatar_url=None,
            bio=None,
        )

    async def fetch_live(self, sec_uid: str) -> DouyinLiveRecord:
        room = await self._fetch_room(sec_uid)
        return DouyinLiveRecord(
            sec_uid=sec_uid,
            observed_at=self._clock(),
            raw_status=room.get("status"),
            source=STREAMGET_DOUYIN_SOURCE,
            room_id=_clean_optional(room.get("id") or room.get("room_id")),
            title=_clean_optional(room.get("title")),
            source_started_at=_parse_started_at(room.get("start_time")),
        )
