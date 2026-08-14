#!/usr/bin/env python3
"""Stage Letter V0.1 — Gate 0A TikHub Douyin live probe.

Commercial technical candidate only. TikHub is an unofficial third-party API;
using it does not by itself establish Douyin authorization for Stage Letter.

The API token MUST come from TIKHUB_API_KEY. Never commit or print the token.
A failure or ambiguous response is UNKNOWN, never OFFLINE unless the provider
returns explicit, trustworthy offline evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TZ_UTC8 = timezone(timedelta(hours=8))
API_BASE = "https://api.tikhub.io"
LIVE_ENDPOINT = "/api/v1/douyin/web/fetch_user_live_videos"
SOURCE_TYPE = "COMMERCIAL_API_CANDIDATE"
SOURCE_PROVIDER = "TIKHUB"
AUTHORIZATION_BASIS = "TIKHUB_TERMS_ONLY_DOUYIN_RIGHTS_UNVERIFIED"
USER_AGENT = "StageLetter-Gate0A/0.1 (+https://github.com/hengxiaopai/stage-letter)"

URL_KEY_HINTS = (
    "flv",
    "hls",
    "m3u8",
    "stream",
    "pull_url",
    "play_url",
    "url",
)

EXPLICIT_OFFLINE_MARKERS = (
    "not live",
    "offline",
    "未开播",
    "暂未开播",
    "直播已结束",
    "已下播",
)


@dataclass(frozen=True)
class Observation:
    schema_version: int
    target_id: str
    label: str
    webcast_id: str
    status: str
    title: str | None
    creator_name: str | None
    room_id: str | None
    stream_url_count: int
    observed_at: str
    source_type: str
    source_provider: str
    authorization_basis: str
    production_approved: bool
    confidence: float
    http_status: int | None
    latency_ms: int
    provider_code: int | str | None
    provider_message: str | None
    error_type: str | None
    evidence: list[str]
    response_sha256: str | None
    response_bytes: int


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def valid_webcast_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,20}", value or ""))


def load_targets(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError("provider_targets.json must contain a 'targets' array")
    return [dict(item) for item in targets]


def iter_nodes(value: Any, path: str = "$", depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 14:
        return
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_nodes(child, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value[:200]):
            yield from iter_nodes(child, f"{path}[{index}]", depth + 1)


def stream_urls(payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for path, value in iter_nodes(payload):
        if not isinstance(value, str):
            continue
        lower_path = path.lower()
        lower_value = value.lower()
        if not any(hint in lower_path for hint in URL_KEY_HINTS):
            continue
        if not (lower_value.startswith("http://") or lower_value.startswith("https://") or lower_value.startswith("//")):
            continue
        if any(token in lower_value for token in (".flv", ".m3u8", "stream", "pull")):
            found.append(value)
    return list(dict.fromkeys(found))


def find_first_scalar(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    wanted = {key.lower() for key in keys}
    for path, value in iter_nodes(payload):
        key = path.rsplit(".", 1)[-1].lower()
        if key not in wanted:
            continue
        if isinstance(value, (str, int)) and str(value) not in ("", "0", "None"):
            return str(value)
    return None


def fetch(webcast_id: str, token: str, timeout: float) -> tuple[int | None, bytes, int, str | None]:
    query = urllib.parse.urlencode({"webcast_id": webcast_id})
    url = f"{API_BASE}{LIVE_ENDPOINT}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(), round((time.perf_counter() - started) * 1000), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        status = int(exc.code)
        kind = "AUTH_ERROR" if status in (401, 403) else "RATE_LIMIT" if status == 429 else f"HTTP_{status}"
        return status, body, round((time.perf_counter() - started) * 1000), kind
    except urllib.error.URLError as exc:
        return None, b"", round((time.perf_counter() - started) * 1000), f"NETWORK:{getattr(exc, 'reason', exc)}"
    except TimeoutError:
        return None, b"", round((time.perf_counter() - started) * 1000), "TIMEOUT"
    except Exception as exc:
        return None, b"", round((time.perf_counter() - started) * 1000), f"UNEXPECTED:{type(exc).__name__}"


def classify(payload: dict[str, Any]) -> tuple[str, float, list[str], str | None, list[str]]:
    provider_code = payload.get("code")
    message = " ".join(
        str(payload.get(key) or "") for key in ("message", "message_zh", "msg")
    ).strip()
    urls = stream_urls(payload)

    if str(provider_code) == "200" and urls:
        return "LIVE", 0.95, [f"provider_code:{provider_code}", f"stream_urls:{len(urls)}"], None, urls

    lowered = message.lower()
    for marker in EXPLICIT_OFFLINE_MARKERS:
        if marker.lower() in lowered:
            return "OFFLINE", 0.85, [f"explicit_provider_offline:{marker}"], None, []

    # Some upstream payloads may expose explicit live_status without stream URLs.
    live_status = find_first_scalar(payload, ("live_status", "status"))
    if str(provider_code) == "200" and live_status is not None:
        normalized = live_status.strip().lower()
        if normalized in {"1", "live", "living", "online"}:
            return "LIVE", 0.80, [f"provider_code:{provider_code}", f"live_status:{live_status}"], None, []
        if normalized in {"0", "2", "offline", "ended"}:
            return "OFFLINE", 0.75, [f"provider_code:{provider_code}", f"live_status:{live_status}"], None, []

    return "UNKNOWN", 0.0, [f"provider_code:{provider_code}", "no_decisive_state_evidence"], "PROVIDER_AMBIGUOUS", []


def invalid_observation(target: dict[str, Any]) -> Observation:
    webcast_id = str(target.get("web_rid", ""))
    return Observation(
        schema_version=1,
        target_id=str(target.get("id", "UNKNOWN")),
        label=str(target.get("label", webcast_id)),
        webcast_id=webcast_id,
        status="UNKNOWN",
        title=None,
        creator_name=None,
        room_id=None,
        stream_url_count=0,
        observed_at=now_iso(),
        source_type=SOURCE_TYPE,
        source_provider=SOURCE_PROVIDER,
        authorization_basis=AUTHORIZATION_BASIS,
        production_approved=False,
        confidence=0.0,
        http_status=None,
        latency_ms=0,
        provider_code=None,
        provider_message=None,
        error_type="INVALID_TARGET",
        evidence=["local_validation_failed"],
        response_sha256=None,
        response_bytes=0,
    )


def probe_target(target: dict[str, Any], token: str, timeout: float) -> Observation:
    webcast_id = str(target.get("web_rid", ""))
    if not valid_webcast_id(webcast_id):
        return invalid_observation(target)

    http_status, body, latency_ms, fetch_error = fetch(webcast_id, token, timeout)
    digest = hashlib.sha256(body).hexdigest() if body else None
    payload: dict[str, Any] = {}
    parse_error: str | None = None

    if body:
        try:
            parsed = json.loads(body.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                payload = parsed
            else:
                parse_error = "NON_OBJECT_JSON"
        except json.JSONDecodeError:
            parse_error = "INVALID_JSON"

    if fetch_error or parse_error:
        status = "UNKNOWN"
        confidence = 0.0
        evidence = [f"fetch_or_parse_error:{fetch_error or parse_error}"]
        error_type = fetch_error or parse_error
        urls: list[str] = []
    else:
        status, confidence, evidence, error_type, urls = classify(payload)

    provider_code = payload.get("code")
    provider_message = payload.get("message_zh") or payload.get("message") or payload.get("msg")

    # Only surface metadata when the provider gave a decisive state.
    title = find_first_scalar(payload, ("title", "room_title")) if status == "LIVE" else None
    creator_name = find_first_scalar(payload, ("nickname", "anchor_name", "display_name")) if status == "LIVE" else None
    room_id = find_first_scalar(payload, ("room_id", "id_str")) if status in ("LIVE", "OFFLINE") else None

    return Observation(
        schema_version=1,
        target_id=str(target.get("id", "UNKNOWN")),
        label=str(target.get("label", webcast_id)),
        webcast_id=webcast_id,
        status=status,
        title=title,
        creator_name=creator_name,
        room_id=room_id,
        stream_url_count=len(urls),
        observed_at=now_iso(),
        source_type=SOURCE_TYPE,
        source_provider=SOURCE_PROVIDER,
        authorization_basis=AUTHORIZATION_BASIS,
        production_approved=False,
        confidence=confidence,
        http_status=http_status,
        latency_ms=latency_ms,
        provider_code=provider_code,
        provider_message=str(provider_message)[:240] if provider_message is not None else None,
        error_type=error_type,
        evidence=evidence,
        response_sha256=digest,
        response_bytes=len(body),
    )


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Stage Letter Gate 0A TikHub probe")
    parser.add_argument("--targets", type=Path, default=here / "provider_targets.json")
    parser.add_argument("--output", type=Path, default=here / "data" / "tikhub-smoke.jsonl")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    token = os.environ.get("TIKHUB_API_KEY", "").strip()
    if not token:
        print("BLOCKED_MISSING_SECRET: set TIKHUB_API_KEY in the execution environment", file=sys.stderr)
        return 3

    try:
        targets = load_targets(args.targets)
    except Exception as exc:
        print(f"target configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    observations: list[Observation] = []
    with args.output.open("w", encoding="utf-8") as handle:
        for target in targets:
            obs = probe_target(target, token, args.timeout)
            observations.append(obs)
            line = json.dumps(asdict(obs), ensure_ascii=False, separators=(",", ":"))
            handle.write(line + "\n")
            print(line)

    counts = {state: sum(item.status == state for item in observations) for state in ("LIVE", "OFFLINE", "UNKNOWN")}
    summary = {
        "observed_at": now_iso(),
        "provider": SOURCE_PROVIDER,
        "authorization_basis": AUTHORIZATION_BASIS,
        "production_approved": False,
        "endpoint": LIVE_ENDPOINT,
        "total": len(observations),
        "states": counts,
        "decisive_live_found": counts["LIVE"] > 0,
        "output": str(args.output),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
