#!/usr/bin/env python3
"""Stage Letter V0.1 — TikHub creator resolve + UID live-status probe.

Primary Gate 0A.2 path:

    nickname / Douyin ID
        -> creator/fetch_user_search (primary)
        -> search/fetch_user_search_v2 (fallback only)
        -> uid + sec_uid
        -> fetch_user_live_info_by_uid
        -> normalized LIVE / OFFLINE / UNKNOWN

Technical evidence only. TikHub remains a commercial technical candidate and
is not production-approved for Stage Letter.

Security:
- reads token only from TIKHUB_API_KEY
- never prints or returns the token
- never returns raw provider payloads
- never returns live stream URLs
- diagnostics expose only response shape/status metadata
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

TZ_UTC8 = timezone(timedelta(hours=8))
API_BASE = os.environ.get("TIKHUB_API_BASE", "https://api.tikhub.io").rstrip("/")
CREATOR_SEARCH_ENDPOINT = "/api/v1/douyin/creator/fetch_user_search"
APP_USER_SEARCH_ENDPOINT = "/api/v1/douyin/search/fetch_user_search_v2"
UID_LIVE_ENDPOINT = "/api/v1/douyin/web/fetch_user_live_info_by_uid"
USER_AGENT = "StageLetter-Gate0A/0.5 (+https://github.com/hengxiaopai/stage-letter)"
SOURCE_TYPE = "COMMERCIAL_API_CANDIDATE"
SOURCE_PROVIDER = "TIKHUB"


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def iter_nodes(value: Any, path: str = "$", depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 16:
        return
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_nodes(child, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value[:300]):
            yield from iter_nodes(child, f"{path}[{index}]", depth + 1)


def normalize_text(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def classify_live_status(value: Any) -> str | None:
    if isinstance(value, bool):
        return "LIVE" if value else "OFFLINE"
    normalized = str(value).strip().lower() if value is not None else ""
    if normalized in {"1", "live", "living", "online", "true"}:
        return "LIVE"
    if normalized in {"0", "offline", "not_live", "false"}:
        return "OFFLINE"
    return None


def provider_error_type(http_status: int | None) -> str:
    if http_status == 400:
        return "BAD_REQUEST_OR_UPSTREAM"
    if http_status == 402:
        return "PAYMENT_REQUIRED"
    if http_status in (401, 403):
        return "AUTH_OR_PERMISSION_ERROR"
    if http_status == 422:
        return "VALIDATION_ERROR"
    if http_status == 429:
        return "RATE_LIMIT"
    if http_status is not None and http_status >= 500:
        return "PROVIDER_SERVER_ERROR"
    return "PROVIDER_ERROR"


def request_json(
    *,
    method: str,
    path: str,
    token: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            http_status = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        http_status = int(exc.code)
    except Exception as exc:
        return {
            "ok": False,
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "provider_code": None,
            "provider_message": None,
            "payload": {},
            "error_type": f"NETWORK_OR_RUNTIME:{type(exc).__name__}",
        }

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        return {
            "ok": False,
            "http_status": http_status,
            "latency_ms": latency_ms,
            "provider_code": None,
            "provider_message": None,
            "payload": {},
            "error_type": "INVALID_JSON",
        }

    provider_code = payload.get("code")
    provider_message = payload.get("message_zh") or payload.get("message") or payload.get("msg")
    successful = http_status == 200 and str(provider_code) == "200"
    return {
        "ok": successful,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "provider_code": provider_code,
        "provider_message": provider_message,
        "payload": payload,
        "error_type": None if successful else provider_error_type(http_status),
    }


def avatar_url(user_info: dict[str, Any]) -> str | None:
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger", "avatar"):
        avatar = user_info.get(key)
        if isinstance(avatar, str) and avatar.startswith(("http://", "https://")):
            return avatar
        if not isinstance(avatar, dict):
            continue
        urls = avatar.get("url_list")
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
        for url_key in ("url", "uri"):
            value = avatar.get(url_key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def unwrap_user_info(node: dict[str, Any]) -> dict[str, Any]:
    for key in ("user_info", "user", "author", "creator"):
        value = node.get(key)
        if isinstance(value, dict):
            return value
    return node


def extract_user_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for _, node in iter_nodes(payload.get("data")):
        if not isinstance(node, dict):
            continue
        user_info = unwrap_user_info(node)
        if not isinstance(user_info, dict):
            continue

        uid = str(
            user_info.get("uid")
            or user_info.get("user_id")
            or user_info.get("id")
            or ""
        ).strip()
        sec_uid = str(
            user_info.get("sec_uid")
            or user_info.get("sec_user_id")
            or user_info.get("sec_user_id_v2")
            or ""
        ).strip()
        nickname = str(
            user_info.get("nickname")
            or user_info.get("nick_name")
            or user_info.get("name")
            or ""
        ).strip()
        unique_id = str(
            user_info.get("unique_id")
            or user_info.get("short_id")
            or user_info.get("aweme_id")
            or user_info.get("douyin_id")
            or ""
        ).strip()

        if not uid or not nickname:
            continue

        key = (uid, sec_uid)
        if key in seen:
            continue
        seen.add(key)

        raw_live_status = user_info.get("live_status")
        candidates.append({
            "uid": uid,
            "sec_uid": sec_uid or None,
            "nickname": nickname,
            "unique_id": unique_id or None,
            "signature": user_info.get("signature") or user_info.get("bio"),
            "follower_count": user_info.get("follower_count") or user_info.get("fans_count"),
            "avatar_url": avatar_url(user_info),
            "raw_live_status": raw_live_status,
            "search_status": classify_live_status(raw_live_status) or "UNKNOWN",
        })
        if len(candidates) >= 20:
            break

    return candidates


def choose_candidate(keyword: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    if not candidates:
        return None, None

    wanted = normalize_text(keyword)
    for candidate in candidates:
        if normalize_text(candidate.get("nickname")) == wanted:
            return candidate, "EXACT_NICKNAME"
    for candidate in candidates:
        if normalize_text(candidate.get("unique_id")) == wanted:
            return candidate, "EXACT_DOUYIN_ID"
    for candidate in candidates:
        nickname = normalize_text(candidate.get("nickname"))
        if wanted and wanted in nickname:
            return candidate, "NICKNAME_CONTAINS"
    return candidates[0], "FIRST_SEARCH_RESULT"


def payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    data_keys = list(data.keys())[:30] if isinstance(data, dict) else []
    status_code = None
    status_msg = None
    for path, value in iter_nodes(data, depth=0):
        key = path.rsplit(".", 1)[-1]
        if status_code is None and key == "status_code" and isinstance(value, (str, int)):
            status_code = value
        if status_msg is None and key in {"status_msg", "status_message"} and isinstance(value, str):
            status_msg = value[:160]
        if status_code is not None and status_msg is not None:
            break
    return {
        "data_type": type(data).__name__,
        "data_keys": data_keys,
        "inner_status_code": status_code,
        "inner_status_message": status_msg,
    }


def search_attempt_summary(call: dict[str, Any], endpoint: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "ok": call.get("ok"),
        "http_status": call.get("http_status"),
        "provider_code": call.get("provider_code"),
        "provider_message": call.get("provider_message"),
        "latency_ms": call.get("latency_ms"),
        "error_type": call.get("error_type"),
        "candidate_count": len(candidates),
        "response_shape": payload_shape(call.get("payload") or {}),
    }


def search_users(keyword: str, token: str, timeout: float = 30.0) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []

    primary = request_json(
        method="GET",
        path=CREATOR_SEARCH_ENDPOINT,
        token=token,
        query={"user_name": keyword},
        timeout=timeout,
    )
    primary_candidates = extract_user_candidates(primary["payload"]) if primary["ok"] else []
    attempts.append(search_attempt_summary(primary, "creator/fetch_user_search", primary_candidates))

    if primary_candidates:
        selected, match_reason = choose_candidate(keyword, primary_candidates)
        return {
            "ok": primary["ok"],
            "http_status": primary["http_status"],
            "latency_ms": primary["latency_ms"],
            "provider_code": primary["provider_code"],
            "provider_message": primary["provider_message"],
            "error_type": primary["error_type"],
            "candidate_count": len(primary_candidates),
            "candidates": primary_candidates,
            "selected": selected,
            "match_reason": match_reason,
            "source_endpoint": "creator/fetch_user_search",
            "attempts": attempts,
        }

    fallback = request_json(
        method="POST",
        path=APP_USER_SEARCH_ENDPOINT,
        token=token,
        body={"keyword": keyword, "cursor": 0},
        timeout=timeout,
    )
    fallback_candidates = extract_user_candidates(fallback["payload"]) if fallback["ok"] else []
    attempts.append(search_attempt_summary(fallback, "search/fetch_user_search_v2", fallback_candidates))
    selected, match_reason = choose_candidate(keyword, fallback_candidates)

    effective = fallback if fallback_candidates or fallback["ok"] else primary
    return {
        "ok": bool(primary["ok"] or fallback["ok"]),
        "http_status": effective["http_status"],
        "latency_ms": primary["latency_ms"] + fallback["latency_ms"],
        "provider_code": effective["provider_code"],
        "provider_message": effective["provider_message"],
        "error_type": None if (primary["ok"] or fallback["ok"]) else (fallback["error_type"] or primary["error_type"]),
        "candidate_count": len(fallback_candidates),
        "candidates": fallback_candidates,
        "selected": selected,
        "match_reason": match_reason,
        "source_endpoint": "search/fetch_user_search_v2:fallback",
        "attempts": attempts,
    }


def find_key_values(payload: dict[str, Any], key_name: str) -> list[Any]:
    found: list[Any] = []
    for path, value in iter_nodes(payload.get("data")):
        key = path.rsplit(".", 1)[-1]
        if key == key_name:
            found.append(value)
    return found


def extract_uid_live_fact(payload: dict[str, Any]) -> dict[str, Any]:
    live_values = find_key_values(payload, "live_status")
    room_values = find_key_values(payload, "room_id")

    raw_live_status = next((value for value in live_values if classify_live_status(value) is not None), None)
    status = classify_live_status(raw_live_status) or "UNKNOWN"
    room_id = None
    for value in room_values:
        text = str(value or "").strip()
        if text and text != "0":
            room_id = text
            break

    return {
        "status": status,
        "raw_live_status": raw_live_status,
        "room_id": room_id,
    }


def probe_uid_live(uid: str, token: str, timeout: float = 30.0) -> dict[str, Any]:
    call = request_json(
        method="GET",
        path=UID_LIVE_ENDPOINT,
        token=token,
        query={"uid": uid},
        timeout=timeout,
    )
    fact = extract_uid_live_fact(call["payload"]) if call["ok"] else {
        "status": "UNKNOWN",
        "raw_live_status": None,
        "room_id": None,
    }
    return {
        "ok": call["ok"],
        "uid": uid,
        **fact,
        "http_status": call["http_status"],
        "latency_ms": call["latency_ms"],
        "provider_code": call["provider_code"],
        "provider_message": call["provider_message"],
        "error_type": call["error_type"] if fact["status"] == "UNKNOWN" else None,
        "source_endpoint": "fetch_user_live_info_by_uid",
        "response_shape": payload_shape(call.get("payload") or {}),
    }


def resolve_and_probe(keyword: str, token: str, timeout: float = 30.0) -> dict[str, Any]:
    observed_at = now_iso()
    search = search_users(keyword, token, timeout)
    selected = search.get("selected")

    if not selected:
        return {
            "ok": False,
            "platform": "douyin",
            "keyword": keyword,
            "status": "UNKNOWN",
            "creator": None,
            "room_id": None,
            "observed_at": observed_at,
            "confidence": 0.0,
            "evidence": ["no_resolved_creator"],
            "search": search,
            "uid_live": None,
            "source_type": SOURCE_TYPE,
            "source_provider": SOURCE_PROVIDER,
            "production_approved": False,
            "error_type": search.get("error_type") or "CREATOR_NOT_RESOLVED",
        }

    uid = str(selected["uid"])
    uid_live = probe_uid_live(uid, token, timeout)

    if uid_live["status"] in ("LIVE", "OFFLINE"):
        status = uid_live["status"]
        confidence = 0.95
        evidence = [
            f"creator_match:{search.get('match_reason')}",
            f"uid_live_status:{uid_live.get('raw_live_status')}",
        ]
        if uid_live.get("room_id"):
            evidence.append("uid_live_room_id_present")
        error_type = None
    elif selected.get("search_status") in ("LIVE", "OFFLINE"):
        status = selected["search_status"]
        confidence = 0.80
        evidence = [
            f"creator_match:{search.get('match_reason')}",
            f"search_live_status:{selected.get('raw_live_status')}",
            "uid_live_endpoint_inconclusive_search_status_used",
        ]
        error_type = "UID_LIVE_INCONCLUSIVE"
    else:
        status = "UNKNOWN"
        confidence = 0.0
        evidence = [
            f"creator_match:{search.get('match_reason')}",
            "no_decisive_live_status",
        ]
        error_type = uid_live.get("error_type") or "NO_DECISIVE_LIVE_STATUS"

    creator = {
        "uid": selected.get("uid"),
        "sec_uid": selected.get("sec_uid"),
        "nickname": selected.get("nickname"),
        "unique_id": selected.get("unique_id"),
        "signature": selected.get("signature"),
        "follower_count": selected.get("follower_count"),
        "avatar_url": selected.get("avatar_url"),
        "match_reason": search.get("match_reason"),
    }

    return {
        "ok": status in ("LIVE", "OFFLINE"),
        "platform": "douyin",
        "keyword": keyword,
        "status": status,
        "creator": creator,
        "room_id": uid_live.get("room_id"),
        "observed_at": observed_at,
        "confidence": confidence,
        "evidence": evidence,
        "search": {
            "http_status": search.get("http_status"),
            "provider_code": search.get("provider_code"),
            "provider_message": search.get("provider_message"),
            "latency_ms": search.get("latency_ms"),
            "candidate_count": search.get("candidate_count"),
            "source_endpoint": search.get("source_endpoint"),
            "attempts": search.get("attempts"),
        },
        "uid_live": uid_live,
        "source_type": SOURCE_TYPE,
        "source_provider": SOURCE_PROVIDER,
        "production_approved": False,
        "error_type": error_type,
    }


def main() -> int:
    token = os.environ.get("TIKHUB_API_KEY", "").strip()
    if not token:
        print("BLOCKED_MISSING_SECRET: set TIKHUB_API_KEY", file=sys.stderr)
        return 3

    keyword = sys.argv[1] if len(sys.argv) > 1 else "X.四五六"
    result = resolve_and_probe(keyword, token)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("LIVE", "OFFLINE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
