"""Evidence-backed HTTP transport for the formal Huya adapter.

The gateway reads the Huya mobile room page and exposes provider records only. It
never imports the legacy top-level platform_adapters package and never converts a
transport/parse failure into OFFLINE.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx

from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_http_failure,
)
from .huya import HuyaIdentityRecord, HuyaLiveRecord, HuyaProfileRecord


HUYA_MOBILE_BASE = "https://m.huya.com"
HUYA_HTML_SOURCE = "huya.mobile_html"

_ROOM_URL_RE = re.compile(r"^https?://(?:(?:www|m)\.)?huya\.com/([1-9]\d{0,14})(?:[/?#].*)?$", re.I)
_ROOM_ID_RE = re.compile(r"^[1-9]\d{0,14}$")
_BODY_CLASS_RE = re.compile(r'<body[^>]*class=["\']([^"\']*)["\']', re.I)
_E_LIVE_STATUS_RE = re.compile(r'["\']eLiveStatus["\']\s*:\s*(\d+)', re.I)
_START_TIME_RE = re.compile(
    r'["\'](?:startTime|start_time|liveStartTime|live_start_time)["\']\s*:\s*(\d{10,})',
    re.I,
)
_TITLE_PATTERNS = (
    re.compile(r'["\'](?:sRoomName|roomName|introduction)["\']\s*:\s*["\']([^"\']+)["\']', re.I),
    re.compile(r"<title>(.*?)</title>", re.I | re.S),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _started_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        return None
    if seconds <= 1_000_000_000:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _optional_title(html: str) -> str | None:
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(html)
        if match:
            text = re.sub(r"\s+", " ", match.group(1)).strip()
            if text:
                return text
    return None


@runtime_checkable
class HuyaHtmlTransport(Protocol):
    async def get_text(self, url: str) -> str: ...


class HttpxHuyaHtmlTransport:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.4 Mobile/15E148 Safari/604.1"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    async def get_text(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.TIMEOUT, "huya.http", detail=type(exc).__name__)
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.NETWORK, "huya.http", detail=type(exc).__name__)
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.UNKNOWN, "huya.http", detail=type(exc).__name__)
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderOperationError(
                classify_http_failure(response.status_code, source="huya.http")
            )
        text = response.text
        if not isinstance(text, str) or not text.strip():
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.SCHEMA_DRIFT,
                    "huya.http",
                    detail="empty/non-text response",
                )
            )
        return text


class HuyaHttpGateway:
    """Concrete HuyaProviderGateway using the mobile room HTML page."""

    def __init__(
        self,
        *,
        transport: HuyaHtmlTransport | None = None,
        clock=_now,
    ) -> None:
        self._transport = transport or HttpxHuyaHtmlTransport()
        if not isinstance(self._transport, HuyaHtmlTransport):
            raise TypeError("transport must implement HuyaHtmlTransport")
        self._clock = clock

    @staticmethod
    def parse_identity(value: str) -> str:
        text = value.strip()
        match = _ROOM_URL_RE.fullmatch(text)
        if match:
            return match.group(1)
        if _ROOM_ID_RE.fullmatch(text):
            return text
        raise ProviderOperationError(
            ProviderFailure(
                ProviderFailureKind.UNKNOWN,
                "huya.identity",
                detail="input is not a supported Huya room identity",
            )
        )

    @staticmethod
    def canonical_url(room_id: str) -> str:
        if not _ROOM_ID_RE.fullmatch(room_id):
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.SCHEMA_DRIFT,
                    "huya.identity",
                    detail="invalid room_id",
                )
            )
        return f"https://www.huya.com/{room_id}"

    async def _html(self, room_id: str) -> str:
        room_id = self.parse_identity(room_id)
        return await self._transport.get_text(f"{HUYA_MOBILE_BASE}/{room_id}")

    @staticmethod
    def _raw_live_status(html: str) -> object:
        """Extract only evidence-backed Huya status signals.

        Later Gate 0B evidence records eLiveStatus=2 with body.liveStatus-on and
        eLiveStatus=1 with body.liveStatus-off. When both signals are present they
        must agree. 0/3 are preserved as raw values for the formal adapter to keep
        UNKNOWN; they are not guessed as OFFLINE.
        """

        body_signal: str | None = None
        body_match = _BODY_CLASS_RE.search(html)
        if body_match:
            classes = body_match.group(1).split()
            if "liveStatus-on" in classes:
                body_signal = "liveStatus-on"
            elif "liveStatus-off" in classes:
                body_signal = "liveStatus-off"

        status_match = _E_LIVE_STATUS_RE.search(html)
        e_status = int(status_match.group(1)) if status_match else None

        if body_signal is not None and e_status is not None:
            expected = 2 if body_signal == "liveStatus-on" else 1
            if e_status != expected:
                raise ProviderOperationError(
                    ProviderFailure(
                        ProviderFailureKind.AMBIGUOUS,
                        HUYA_HTML_SOURCE,
                        detail="body/eLiveStatus conflict",
                    )
                )
            return e_status

        if e_status is not None:
            return e_status
        if body_signal is not None:
            return body_signal

        raise ProviderOperationError(
            ProviderFailure(
                ProviderFailureKind.SCHEMA_DRIFT,
                HUYA_HTML_SOURCE,
                detail="no evidence-backed live status field",
            )
        )

    async def resolve_identity(self, input: str) -> HuyaIdentityRecord:
        room_id = self.parse_identity(input)
        return HuyaIdentityRecord(
            room_id=room_id,
            canonical_url=self.canonical_url(room_id),
        )

    async def fetch_profile(self, room_id: str) -> HuyaProfileRecord:
        room_id = self.parse_identity(room_id)
        # A fetch proves that the room surface is currently reachable. No profile
        # field is invented from weak HTML heuristics in this slice.
        await self._html(room_id)
        return HuyaProfileRecord(room_id=room_id, observed_at=self._clock())

    async def fetch_live(self, room_id: str) -> HuyaLiveRecord:
        room_id = self.parse_identity(room_id)
        html = await self._html(room_id)
        start_match = _START_TIME_RE.search(html)
        return HuyaLiveRecord(
            room_id=room_id,
            observed_at=self._clock(),
            raw_live_status=self._raw_live_status(html),
            source=HUYA_HTML_SOURCE,
            title=_optional_title(html),
            source_started_at=_started_at(start_match.group(1) if start_match else None),
        )
