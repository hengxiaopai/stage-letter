#!/usr/bin/env python3
"""Stage Letter Gate 0A — F2 direct Douyin live-status second-source probe.

Purpose
-------
Validate a second, self-hosted Douyin observation path for explicit OFFLINE
semantics. The candidate is Johnserf-Seed/f2, which targets Douyin's web
endpoint:

    https://live.douyin.com/webcast/distribution/check_user_live_status/

F2's current filter defines the returned user_live.live_status as:

    1 -> live
    0 -> not live

Gate rule: only an explicit 0/1 is normalized to OFFLINE/LIVE. Missing data,
request failures, captcha/login/rate-limit behavior, parser drift, or any other
value MUST remain UNKNOWN.

This is an experiment only. It is not production-approved and does not mutate
LiveSession or notification state.

Dependency
----------
Use F2 in an isolated Gate environment. The research baseline inspected for
this probe is Johnserf-Seed/f2 main commit:

    7dab3e2ffffaa2535834d28fca99dbc2e89fa9d3

Security
--------
- Optional Douyin cookie is read only from DOUYIN_COOKIE.
- Cookie contents are never printed or returned.
- First Gate run SHOULD use no login cookie. A cookie-backed run may be useful
  diagnostically but does not prove the ordinary-public unauthenticated path.
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
SOURCE_TYPE = "SELF_HOSTED_WEB_CANDIDATE"
SOURCE_PROVIDER = "F2_DIRECT_DOUYIN_WEB"
SOURCE_ENDPOINT = "https://live.douyin.com/webcast/distribution/check_user_live_status/"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def classify_explicit_live_status(value: Any) -> str:
    if isinstance(value, bool):
        # Do not silently reinterpret booleans as numeric provider states.
        return "UNKNOWN"
    text = str(value).strip() if value is not None else ""
    if text == "1":
        return "LIVE"
    if text == "0":
        return "OFFLINE"
    return "UNKNOWN"


def blocked_missing_f2(uid: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "platform": "douyin",
        "uid": uid,
        "status": "UNKNOWN",
        "raw_live_status": None,
        "room_id": None,
        "api_status_code": None,
        "observed_at": now_iso(),
        "source_type": SOURCE_TYPE,
        "source_provider": SOURCE_PROVIDER,
        "source_endpoint": SOURCE_ENDPOINT,
        "f2_version": None,
        "cookie_configured": bool(os.environ.get("DOUYIN_COOKIE", "").strip()),
        "production_approved": False,
        "error_type": "BLOCKED_MISSING_F2",
        "message": type(exc).__name__,
    }


async def probe(uid: str) -> dict[str, Any]:
    try:
        from f2.apps.douyin.crawler import DouyinCrawler
        from f2.apps.douyin.filter import UserLiveStatusFilter
        from f2.apps.douyin.model import UserLiveStatus
    except Exception as exc:
        return blocked_missing_f2(uid, exc)

    try:
        f2_version = metadata.version("f2")
    except metadata.PackageNotFoundError:
        f2_version = "source-or-editable"

    cookie = os.environ.get("DOUYIN_COOKIE", "").strip()
    user_agent = os.environ.get("DOUYIN_USER_AGENT", DEFAULT_UA).strip() or DEFAULT_UA

    kwargs = {
        "cookie": cookie,
        "headers": {
            "User-Agent": user_agent,
            "Referer": "https://live.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        },
        "proxies": {"http://": None, "https://": None},
    }

    try:
        async with DouyinCrawler(kwargs) as crawler:
            response = await crawler.fetch_user_live_status(UserLiveStatus(user_ids=uid))
        filtered = UserLiveStatusFilter(response)
        raw_status = filtered.live_status
        status = classify_explicit_live_status(raw_status)
        room_id = filtered.room_id
        api_status_code = filtered.api_status_code
        returned_user_id = filtered.user_id
    except Exception as exc:
        return {
            "ok": False,
            "platform": "douyin",
            "uid": uid,
            "status": "UNKNOWN",
            "raw_live_status": None,
            "room_id": None,
            "api_status_code": None,
            "observed_at": now_iso(),
            "source_type": SOURCE_TYPE,
            "source_provider": SOURCE_PROVIDER,
            "source_endpoint": SOURCE_ENDPOINT,
            "f2_version": f2_version,
            "cookie_configured": bool(cookie),
            "production_approved": False,
            "error_type": "F2_REQUEST_OR_PARSE_ERROR",
            "message": type(exc).__name__,
        }

    evidence: list[str] = []
    error_type = None
    confidence = 0.0

    if status in ("LIVE", "OFFLINE"):
        evidence.append(f"explicit_user_live_status:{raw_status}")
        confidence = 0.95
        if status == "LIVE" and room_id:
            evidence.append("room_id_present")
    else:
        evidence.append("no_explicit_0_or_1_live_status")
        error_type = "NO_DECISIVE_LIVE_STATUS"

    return {
        "ok": status in ("LIVE", "OFFLINE"),
        "platform": "douyin",
        "uid": uid,
        "returned_user_id": returned_user_id,
        "status": status,
        "raw_live_status": raw_status,
        "room_id": str(room_id) if room_id not in (None, "", 0, "0") else None,
        "api_status_code": api_status_code,
        "observed_at": now_iso(),
        "confidence": confidence,
        "evidence": evidence,
        "source_type": SOURCE_TYPE,
        "source_provider": SOURCE_PROVIDER,
        "source_endpoint": SOURCE_ENDPOINT,
        "f2_version": f2_version,
        "cookie_configured": bool(cookie),
        "production_approved": False,
        "error_type": error_type,
    }


def valid_uid(value: str) -> bool:
    return value.isdigit() and 5 <= len(value) <= 30


def main() -> int:
    uid = (sys.argv[1] if len(sys.argv) > 1 else "2206033664807300").strip()
    if not valid_uid(uid):
        print(json.dumps({
            "ok": False,
            "platform": "douyin",
            "uid": uid,
            "status": "UNKNOWN",
            "error_type": "INVALID_UID",
        }, ensure_ascii=False, indent=2))
        return 2

    result = asyncio.run(probe(uid))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("LIVE", "OFFLINE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
