#!/usr/bin/env python3
"""Stage Letter V0.1 — TikHub live-search positive-control probe.

Uses TikHub's Douyin live search endpoint, which the provider documents as
returning live-stream content only. This is Gate 0A evidence, not production
approval.

Security:
- reads token only from TIKHUB_API_KEY
- never prints token
- never prints stream URLs
- outputs normalized live-room evidence only
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

API_URL = "https://api.tikhub.io/api/v1/douyin/search/fetch_live_search_v1"
TZ_UTC8 = timezone(timedelta(hours=8))
USER_AGENT = "StageLetter-Gate0A/0.1 (+https://github.com/hengxiaopai/stage-letter)"


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def iter_nodes(value: Any, path: str = "$", depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 14:
        return
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_nodes(child, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        for i, child in enumerate(value[:200]):
            yield from iter_nodes(child, f"{path}[{i}]", depth + 1)


def count_stream_urls(value: Any) -> int:
    count = 0
    for path, node in iter_nodes(value):
        if not isinstance(node, str):
            continue
        lower_path = path.lower()
        lower_value = node.lower()
        if not any(k in lower_path for k in ("stream", "pull_url", "flv", "hls", "m3u8")):
            continue
        if lower_value.startswith(("http://", "https://", "//")):
            count += 1
    return count


def parse_rawdata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def find_live_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        live = candidate.get("lives") if isinstance(candidate.get("lives"), dict) else candidate
        if not isinstance(live, dict):
            return

        author = live.get("author") if isinstance(live.get("author"), dict) else {}
        raw = parse_rawdata(live.get("rawdata"))

        uid = str(author.get("uid") or live.get("uid") or "")
        nickname = str(author.get("nickname") or live.get("nickname") or "")
        room_id = str(live.get("room_id") or raw.get("id_str") or raw.get("id") or "")
        title = str(raw.get("title") or live.get("title") or "")
        user_count = raw.get("user_count")
        if user_count is None and isinstance(raw.get("stats"), dict):
            user_count = raw["stats"].get("total_user")

        stream_url_count = count_stream_urls(raw or live)
        if not room_id and not uid and stream_url_count == 0:
            return

        key = (uid, room_id)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "status": "LIVE",
            "uid": uid or None,
            "nickname": nickname or None,
            "room_id": room_id or None,
            "title": title or None,
            "viewer_count": user_count,
            "stream_url_count": stream_url_count,
            "confidence": 0.95 if stream_url_count > 0 else 0.90,
            "evidence": ["tikhub_live_search_result", f"stream_urls:{stream_url_count}"],
        })

    data = payload.get("data")
    if isinstance(data, dict):
        result_list = data.get("data")
        if isinstance(result_list, list):
            for entry in result_list:
                add_candidate(entry)
        for _, node in iter_nodes(data):
            if isinstance(node, dict) and ("lives" in node or "room_id" in node):
                add_candidate(node)
    elif isinstance(data, list):
        for entry in data:
            add_candidate(entry)

    return items


def fetch_live_search(keyword: str, token: str, timeout: float = 20.0) -> dict[str, Any]:
    body = json.dumps({
        "keyword": keyword,
        "cursor": 0,
        "sort_type": "0",
        "publish_time": "0",
        "filter_duration": "0",
        "content_type": "1",
        "search_id": "",
        "backtrace": "",
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    except Exception as exc:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "error_type": type(exc).__name__,
            "message": str(exc)[:200],
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "observed_at": now_iso(),
        }

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "http_status": status,
            "error_type": "INVALID_JSON",
            "latency_ms": latency_ms,
            "observed_at": now_iso(),
        }

    provider_code = payload.get("code") if isinstance(payload, dict) else None
    provider_message = None
    if isinstance(payload, dict):
        provider_message = payload.get("message_zh") or payload.get("message") or payload.get("msg")
    rooms = find_live_items(payload if isinstance(payload, dict) else {})

    return {
        "ok": status == 200 and str(provider_code) == "200",
        "keyword": keyword,
        "status": "LIVE" if rooms else "UNKNOWN",
        "live_count": len(rooms),
        "rooms": rooms,
        "http_status": status,
        "provider_code": provider_code,
        "provider_message": provider_message,
        "latency_ms": latency_ms,
        "observed_at": now_iso(),
        "source_type": "COMMERCIAL_API_CANDIDATE",
        "source_provider": "TIKHUB",
        "production_approved": False,
        "error_type": None if rooms else "NO_LIVE_RESULTS_PARSED",
    }


def main() -> int:
    token = os.environ.get("TIKHUB_API_KEY", "").strip()
    if not token:
        print("BLOCKED_MISSING_SECRET: set TIKHUB_API_KEY", file=sys.stderr)
        return 3
    keyword = sys.argv[1] if len(sys.argv) > 1 else "游戏"
    result = fetch_live_search(keyword, token)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
