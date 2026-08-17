#!/usr/bin/env python3
"""Stage Letter Gate 0A — StreamGet Douyin status second-source probe.

Purpose
-------
Validate an independent, local Douyin observation path against known OFFLINE
and LIVE controls using StreamGet's explicit room status.

StreamGet's current Douyin implementation treats room status 2 as live and
returns status 4 for a non-live room. For this Gate experiment we normalize
only these explicit values:

    2 -> LIVE
    4 -> OFFLINE

Any missing status, exception, request/parse failure, risk-control behavior, or
other value MUST remain UNKNOWN.

Two input modes are supported:
- PROFILE: https://www.douyin.com/user/<sec_uid>  (preferred for monitoring)
- LIVE_URL: https://live.douyin.com/<web_rid-or-douyin-id>

The PROFILE path is preferred after Gate evidence showed stable repeated
OFFLINE/LIVE classification while one historical numeric live-room URL became
intermittently unparseable for an OFFLINE creator.

This mapping remains experimental. It is not production-approved and does not
mutate LiveSession or notification state.

Security
--------
- Optional Douyin cookie is read only from DOUYIN_COOKIE.
- Cookie contents are never printed or returned.
- Gate runs should default to no login cookie.
- Raw provider payload is not returned.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from importlib import metadata
from typing import Any

TZ_UTC8 = timezone(timedelta(hours=8))
SOURCE_TYPE = "SELF_HOSTED_STREAM_CANDIDATE"
SOURCE_PROVIDER = "STREAMGET_DOUYIN_WEB"


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def classify_room_status(value: Any) -> str:
    if isinstance(value, bool):
        return "UNKNOWN"
    text = str(value).strip() if value is not None else ""
    if text == "2":
        return "LIVE"
    if text == "4":
        return "OFFLINE"
    return "UNKNOWN"


def input_mode(value: str) -> str | None:
    value = value.strip()
    if value.startswith("https://www.douyin.com/user/") and len(value) <= 500:
        return "PROFILE"
    if value.startswith("https://live.douyin.com/") and len(value) <= 300:
        return "LIVE_URL"
    return None


async def probe(url: str) -> dict[str, Any]:
    mode = input_mode(url)
    if mode is None:
        return {
            "ok": False,
            "platform": "douyin",
            "url": url,
            "input_mode": None,
            "status": "UNKNOWN",
            "raw_room_status": None,
            "observed_at": now_iso(),
            "source_type": SOURCE_TYPE,
            "source_provider": SOURCE_PROVIDER,
            "streamget_version": None,
            "cookie_configured": bool(os.environ.get("DOUYIN_COOKIE", "").strip()),
            "production_approved": False,
            "error_type": "INVALID_DOUYIN_INPUT_URL",
        }

    try:
        from streamget import DouyinLiveStream
    except Exception as exc:
        return {
            "ok": False,
            "platform": "douyin",
            "url": url,
            "input_mode": mode,
            "status": "UNKNOWN",
            "raw_room_status": None,
            "observed_at": now_iso(),
            "source_type": SOURCE_TYPE,
            "source_provider": SOURCE_PROVIDER,
            "streamget_version": None,
            "cookie_configured": bool(os.environ.get("DOUYIN_COOKIE", "").strip()),
            "production_approved": False,
            "error_type": "BLOCKED_MISSING_STREAMGET",
            "message": type(exc).__name__,
        }

    try:
        version = metadata.version("streamget")
    except metadata.PackageNotFoundError:
        version = "source-or-editable"

    cookie = os.environ.get("DOUYIN_COOKIE", "").strip()

    try:
        live = DouyinLiveStream(cookies=cookie or None)
        if mode == "PROFILE":
            room = await live.fetch_app_stream_data(url)
        else:
            room = await live.fetch_web_stream_data(url)

        raw_status = room.get("status")
        status = classify_room_status(raw_status)

        stream_obj = None
        if status == "LIVE":
            # Positive LIVE should also survive StreamGet's own stream wrapping.
            stream_obj = await live.fetch_stream_url(room, "OD")

        anchor_name = room.get("anchor_name")
        title = room.get("title")
        live_url = room.get("live_url")
        room_id = room.get("id") or room.get("room_id")

        m3u8_present = False
        flv_present = False
        if stream_obj is not None:
            m3u8_present = bool(getattr(stream_obj, "m3u8_url", None))
            flv_present = bool(getattr(stream_obj, "flv_url", None))

    except Exception as exc:
        return {
            "ok": False,
            "platform": "douyin",
            "url": url,
            "input_mode": mode,
            "status": "UNKNOWN",
            "raw_room_status": None,
            "observed_at": now_iso(),
            "source_type": SOURCE_TYPE,
            "source_provider": SOURCE_PROVIDER,
            "streamget_version": version,
            "cookie_configured": bool(cookie),
            "production_approved": False,
            "error_type": "STREAMGET_REQUEST_OR_PARSE_ERROR",
            "message": type(exc).__name__,
        }

    evidence: list[str] = []
    error_type = None
    confidence = 0.0

    if status == "LIVE":
        evidence.append(f"explicit_room_status:{raw_status}")
        if m3u8_present or flv_present:
            evidence.append("stream_url_present")
            confidence = 0.95
        else:
            confidence = 0.8
    elif status == "OFFLINE":
        evidence.append(f"explicit_room_status:{raw_status}")
        confidence = 0.9
    else:
        evidence.append("no_explicit_supported_room_status")
        error_type = "NO_DECISIVE_ROOM_STATUS"

    return {
        "ok": status in ("LIVE", "OFFLINE"),
        "platform": "douyin",
        "url": url,
        "input_mode": mode,
        "status": status,
        "raw_room_status": raw_status,
        "anchor_name": anchor_name,
        "title": title,
        "live_url": live_url,
        "room_id": room_id,
        "m3u8_present": m3u8_present,
        "flv_present": flv_present,
        "observed_at": now_iso(),
        "confidence": confidence,
        "evidence": evidence,
        "source_type": SOURCE_TYPE,
        "source_provider": SOURCE_PROVIDER,
        "streamget_version": version,
        "cookie_configured": bool(cookie),
        "production_approved": False,
        "error_type": error_type,
    }


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else "https://live.douyin.com/975645387460").strip()
    result = asyncio.run(probe(url))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("LIVE", "OFFLINE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
