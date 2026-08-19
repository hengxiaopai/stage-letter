"""Evidence-backed HTTP transport for the formal Douyu adapter.

The gateway reads the Douyu room HTML and exposes provider records only. It never
imports the legacy top-level platform_adapters package and never converts a
transport/parse failure into OFFLINE.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx

from .douyu import DouyuIdentityRecord, DouyuLiveRecord, DouyuProfileRecord
from .failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_http_failure,
)


DOUYU_BASE = "https://www.douyu.com"
DOUYU_HTML_SOURCE = "douyu.desktop_html"

_ROOM_URL_RE = re.compile(r"^https?://(?:www\.)?douyu\.com/([1-9]\d{0,11})(?:[/?#].*)?$", re.I)
_ROOM_ID_RE = re.compile(r"^[1-9]\d{0,11}$")
_SHOW_STATUS_RE = re.compile(r'\\?["\']show_status\\?["\']\s*:\s*(\d+)', re.I)
_SHOW_STATUS_CAMEL_RE = re.compile(r'\\?["\']showStatus\\?["\']\s*:\s*["\']?(\d+)["\']?', re.I)
_START_TIME_RE = re.compile(
    r'\\?["\'](?:start_time|roomStartTime|liveStartTime|show_start_time)\\?["\']\s*:\s*(\d{10,})',
    re.I,
)
_TITLE_PATTERNS = (
    re.compile(r'\\?["\'](?:room_name|roomName|rn)\\?["\']\s*:\s*["\']([^"\']+)["\']', re.I),
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
class DouyuHtmlTransport(Protocol):
    async def get_text(self, url: str) -> str: ...


class HttpxDouyuHtmlTransport:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyu.com/",
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
                ProviderFailure(ProviderFailureKind.TIMEOUT, "douyu.http", detail=type(exc).__name__)
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.NETWORK, "douyu.http", detail=type(exc).__name__)
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderOperationError(
                ProviderFailure(ProviderFailureKind.UNKNOWN, "douyu.http", detail=type(exc).__name__)
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderOperationError(
                classify_http_failure(response.status_code, source="douyu.http")
            )
        text = response.text
        if not isinstance(text, str) or not text.strip():
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.SCHEMA_DRIFT,
                    "douyu.http",
                    detail="empty/non-text response",
                )
            )
        return text


class DouyuHttpGateway:
    """Concrete DouyuProviderGateway using room HTML."""

    def __init__(
        self,
        *,
        transport: DouyuHtmlTransport | None = None,
        clock=_now,
    ) -> None:
        self._transport = transport or HttpxDouyuHtmlTransport()
        if not isinstance(self._transport, DouyuHtmlTransport):
            raise TypeError("transport must implement DouyuHtmlTransport")
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
                "douyu.identity",
                detail="input is not a supported Douyu room identity",
            )
        )

    @staticmethod
    def canonical_url(room_id: str) -> str:
        if not _ROOM_ID_RE.fullmatch(room_id):
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.SCHEMA_DRIFT,
                    "douyu.identity",
                    detail="invalid room_id",
                )
            )
        return f"https://www.douyu.com/{room_id}"

    async def _html(self, room_id: str) -> str:
        room_id = self.parse_identity(room_id)
        return await self._transport.get_text(self.canonical_url(room_id))

    @staticmethod
    def _raw_live_status(html: str) -> int:
        """Extract only decisive show_status/showStatus evidence.

        Gate 0B evidence supports 1 -> LIVE and 2 -> OFFLINE. Values 0/3/4 stay
        raw for the formal adapter to normalize as UNKNOWN. videoLoop and generic
        isLiveBroadcast fallbacks are intentionally ignored because they do not
        prove that the creator is actually broadcasting now.
        """

        values: list[int] = []
        for pattern in (_SHOW_STATUS_RE, _SHOW_STATUS_CAMEL_RE):
            match = pattern.search(html)
            if match:
                values.append(int(match.group(1)))

        if not values:
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.SCHEMA_DRIFT,
                    DOUYU_HTML_SOURCE,
                    detail="no evidence-backed show_status field",
                )
            )
        if len(set(values)) > 1:
            raise ProviderOperationError(
                ProviderFailure(
                    ProviderFailureKind.AMBIGUOUS,
                    DOUYU_HTML_SOURCE,
                    detail="conflicting show_status fields",
                )
            )
        return values[0]

    async def resolve_identity(self, input: str) -> DouyuIdentityRecord:
        room_id = self.parse_identity(input)
        return DouyuIdentityRecord(
            room_id=room_id,
            canonical_url=self.canonical_url(room_id),
        )

    async def fetch_profile(self, room_id: str) -> DouyuProfileRecord:
        room_id = self.parse_identity(room_id)
        await self._html(room_id)
        return DouyuProfileRecord(room_id=room_id, observed_at=self._clock())

    async def fetch_live(self, room_id: str) -> DouyuLiveRecord:
        room_id = self.parse_identity(room_id)
        html = await self._html(room_id)
        start_match = _START_TIME_RE.search(html)
        return DouyuLiveRecord(
            room_id=room_id,
            observed_at=self._clock(),
            raw_live_status=self._raw_live_status(html),
            source=DOUYU_HTML_SOURCE,
            title=_optional_title(html),
            source_started_at=_started_at(start_match.group(1) if start_match else None),
        )
