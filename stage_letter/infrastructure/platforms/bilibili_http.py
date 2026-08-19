"""Evidence-backed HTTP transport for the formal Bilibili adapter.

The gateway uses the same unauthenticated Bilibili live-room endpoints already
validated in Gate 0B evidence, but exposes only formal provider records. It never
imports the legacy top-level platform_adapters package.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx

from .bilibili import (
    BilibiliIdentityRecord,
    BilibiliLiveRecord,
    BilibiliProfileRecord,
)
from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_http_failure,
)


BILIBILI_API_BASE = "https://api.live.bilibili.com"
BILIBILI_UID_SOURCE = "bilibili.getRoomInfoOld"
BILIBILI_ROOM_SOURCE = "bilibili.room_init"

_SPACE_RE = re.compile(r"^https?://space\.bilibili\.com/(\d+)(?:[/?#].*)?$", re.I)
_LIVE_RE = re.compile(r"^https?://live\.bilibili\.com/(\d+)(?:[/?#].*)?$", re.I)
_NUMERIC_RE = re.compile(r"^[1-9]\d{0,19}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_id(value: object, *, field: str, source: str) -> str:
    if isinstance(value, bool):
        raise ProviderOperationError(
            ProviderFailure(ProviderFailureKind.SCHEMA_DRIFT, source, detail=f"invalid {field}")
        )
    text = str(value).strip() if value is not None else ""
    if not _NUMERIC_RE.fullmatch(text):
        raise ProviderOperationError(
            ProviderFailure(ProviderFailureKind.SCHEMA_DRIFT, source, detail=f"invalid {field}")
        )
    return text


def _started_at(value: object) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 1_000_000_000:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _optional_provider_uid(
    data: dict[str, object],
    *,
    expected_uid: str,
    source: str,
) -> None:
    """Validate provider uid only when the endpoint actually returns one.

    getRoomInfoOld is keyed by the requested mid and commonly omits uid from its
    data object. Absence is therefore not schema drift. If an explicit uid is
    present, it remains useful mismatch evidence and must agree with the request.
    """

    raw_uid = data.get("uid")
    if raw_uid is None:
        return
    provider_uid = _positive_id(raw_uid, field="uid", source=source)
    if provider_uid != expected_uid:
        raise ProviderOperationError(
            ProviderFailure(
                ProviderFailureKind.AMBIGUOUS,
                source,
                detail="provider uid mismatch",
            )
        )


def _uid_live_status(data: dict[str, object]) -> object:
    """Read creator-live status without conflating carousel/replay activity.

    Current getRoomInfoOld responses expose creator-live status and carousel state
    as separate fields. Stage Letter's canonical LIVE means the creator is
    actually broadcasting, so roundStatus must never promote an otherwise
    non-live creator into LIVE.
    """

    if "live_status" in data:
        return data.get("live_status")
    return data.get("liveStatus")


@runtime_checkable
class BilibiliJsonTransport(Protocol):
    async def get_json(self, path: str, params: dict[str, object]) -> dict[str, object]: ...


class HttpxBilibiliJsonTransport:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://live.bilibili.com/",
        }

    async def get_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        url = f"{BILIBILI_API_BASE}{path}"
        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.TIMEOUT, "bilibili.http", detail=type(exc).__name__)
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.NETWORK, "bilibili.http", detail=type(exc).__name__)
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.UNKNOWN, "bilibili.http", detail=type(exc).__name__)
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderOperationError(
                classify_http_failure(response.status_code, source="bilibili.http")
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.PARSE_ERROR, "bilibili.http", detail="non-json response")
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.SCHEMA_DRIFT, "bilibili.http", detail="non-dict payload")
            )
        return payload


class BilibiliHttpGateway:
    """Concrete BilibiliProviderGateway using uid/room live APIs."""

    def __init__(
        self,
        *,
        transport: BilibiliJsonTransport | None = None,
        clock=_now,
    ) -> None:
        self._transport = transport or HttpxBilibiliJsonTransport()
        if not isinstance(self._transport, BilibiliJsonTransport):
            raise TypeError("transport must implement BilibiliJsonTransport")
        self._clock = clock

    @staticmethod
    def parse_identity(value: str) -> tuple[str, str]:
        text = value.strip()
        match = _SPACE_RE.fullmatch(text)
        if match:
            return "uid", match.group(1)
        match = _LIVE_RE.fullmatch(text)
        if match:
            return "room", match.group(1)
        if _NUMERIC_RE.fullmatch(text):
            return "uid", text
        raise ProviderOperationError(
            ProviderFailure(
                ProviderFailureKind.UNKNOWN,
                "bilibili.identity",
                detail="input is not a supported Bilibili uid/space/live identity",
            )
        )

    @staticmethod
    def canonical_profile_url(uid: str) -> str:
        uid = _positive_id(uid, field="uid", source="bilibili.identity")
        return f"https://space.bilibili.com/{uid}"

    async def _data(self, path: str, params: dict[str, object], *, source: str) -> dict[str, object]:
        payload = await self._transport.get_json(path, params)
        code = payload.get("code")
        if code != 0:
            kind = ProviderFailureKind.NOT_FOUND if code == 1 else ProviderFailureKind.UNKNOWN
            raise ProviderOperationError(
                ProviderFailure(kind, source, provider_code=code, detail=_optional_text(payload.get("msg")))
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.SCHEMA_DRIFT, source, detail="missing data object")
            )
        return data

    async def _by_uid(self, uid: str) -> dict[str, object]:
        uid = _positive_id(uid, field="uid", source=BILIBILI_UID_SOURCE)
        return await self._data(
            "/room/v1/Room/getRoomInfoOld",
            {"mid": uid},
            source=BILIBILI_UID_SOURCE,
        )

    async def _by_room(self, room_id: str) -> dict[str, object]:
        room_id = _positive_id(room_id, field="room_id", source=BILIBILI_ROOM_SOURCE)
        return await self._data(
            "/room/v1/Room/room_init",
            {"id": room_id},
            source=BILIBILI_ROOM_SOURCE,
        )

    async def resolve_identity(self, input: str) -> BilibiliIdentityRecord:
        kind, value = self.parse_identity(input)
        data = await (self._by_uid(value) if kind == "uid" else self._by_room(value))

        if kind == "uid":
            _optional_provider_uid(data, expected_uid=value, source="bilibili.resolve")
            uid = value
        else:
            uid = _positive_id(data.get("uid"), field="uid", source="bilibili.resolve")

        room_id = _optional_text(data.get("roomid") or data.get("room_id"))
        return BilibiliIdentityRecord(
            uid=uid,
            room_id=room_id,
            canonical_url=self.canonical_profile_url(uid),
        )

    async def fetch_profile(self, uid: str) -> BilibiliProfileRecord:
        uid = _positive_id(uid, field="uid", source=BILIBILI_UID_SOURCE)
        data = await self._by_uid(uid)
        _optional_provider_uid(data, expected_uid=uid, source=BILIBILI_UID_SOURCE)
        return BilibiliProfileRecord(uid=uid, observed_at=self._clock())

    async def fetch_live(self, uid: str) -> BilibiliLiveRecord:
        uid = _positive_id(uid, field="uid", source=BILIBILI_UID_SOURCE)
        data = await self._by_uid(uid)
        _optional_provider_uid(data, expected_uid=uid, source=BILIBILI_UID_SOURCE)
        return BilibiliLiveRecord(
            uid=uid,
            observed_at=self._clock(),
            raw_live_status=_uid_live_status(data),
            source=BILIBILI_UID_SOURCE,
            room_id=_optional_text(data.get("roomid") or data.get("room_id")),
            title=_optional_text(data.get("title")),
            source_started_at=_started_at(data.get("live_time")),
        )
