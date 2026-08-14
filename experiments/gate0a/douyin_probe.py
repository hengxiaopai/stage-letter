#!/usr/bin/env python3
"""Stage Letter V0.1 — Gate 0A Douyin public-web probe.

Experimental evidence collector only. It intentionally does NOT implement
anti-bot/signature bypasses and it is NOT approved as a production source.

Design invariant: an unavailable/blocked/ambiguous probe is UNKNOWN, never
silently coerced to OFFLINE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TZ_UTC8 = timezone(timedelta(hours=8))
SOURCE_TYPE = "PUBLIC_WEB_PROBE"
SOURCE_PROVIDER = "DOUYIN_WEB"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

RISK_MARKERS = (
    "captcha",
    "verifycenter",
    "verify_center",
    "security-check",
    "risk control",
    "访问过于频繁",
    "安全验证",
    "请完成验证",
    "该内容暂时无法查看",
)

# Only explicit human-visible offline phrases are accepted as OFFLINE evidence.
# Generic JSON numbers/status fields are deliberately NOT interpreted here,
# because their semantics can change and have conflicted across implementations.
OFFLINE_VISIBLE_RE = re.compile(
    r">[^<>]{0,40}(直播已结束|主播暂未开播|暂未开播|当前未开播)[^<>]{0,40}<",
    re.IGNORECASE,
)

# A LIVE verdict requires multiple stream-specific payload signals. This is
# intentionally conservative: ambiguous HTTP 200 pages remain UNKNOWN.
LIVE_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("stream_url", re.compile(r'"stream_url"\s*:\s*\{', re.IGNORECASE)),
    ("hls_pull_url_map", re.compile(r'"hls_pull_url_map"\s*:\s*\{', re.IGNORECASE)),
    ("live_core_sdk_data", re.compile(r'"live_core_sdk_data"\s*:\s*\{', re.IGNORECASE)),
    ("pull_data", re.compile(r'"pull_data"\s*:\s*\{', re.IGNORECASE)),
    ("stream_data", re.compile(r'"stream_data"\s*:', re.IGNORECASE)),
)


@dataclass(frozen=True)
class FetchResult:
    http_status: int | None
    body: bytes
    latency_ms: int
    error_type: str | None
    error_detail: str | None


@dataclass(frozen=True)
class Observation:
    schema_version: int
    target_id: str
    target_kind: str
    label: str
    platform: str
    web_rid: str
    status: str
    creator_name: str | None
    title: str | None
    room_id: str | None
    room_url: str
    source_started_at: str | None
    observed_at: str
    source_type: str
    source_provider: str
    confidence: float
    http_status: int | None
    latency_ms: int
    error_type: str | None
    error_detail: str | None
    evidence: list[str]
    response_sha256: str | None
    response_bytes: int
    expected: str
    expectation_met: bool | None


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def valid_web_rid(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,20}", value or ""))


def fetch_room(url: str, timeout: float) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": "https://live.douyin.com/",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return FetchResult(
                http_status=int(response.status),
                body=body,
                latency_ms=round((time.perf_counter() - started) * 1000),
                error_type=None,
                error_detail=None,
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        status = int(exc.code)
        if status == 429:
            error_type = "RATE_LIMIT"
        elif status == 403:
            error_type = "FORBIDDEN_OR_RISK_CONTROL"
        elif status == 404:
            error_type = "HTTP_NOT_FOUND"
        elif 500 <= status <= 599:
            error_type = "UPSTREAM_5XX"
        else:
            error_type = "HTTP_ERROR"
        return FetchResult(
            http_status=status,
            body=body,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type=error_type,
            error_detail=f"HTTP {status}",
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        name = type(reason).__name__.upper()
        error_type = "TIMEOUT" if "TIMEOUT" in name else "NETWORK_ERROR"
        return FetchResult(
            http_status=None,
            body=b"",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type=error_type,
            error_detail=str(reason)[:300],
        )
    except TimeoutError as exc:
        return FetchResult(
            http_status=None,
            body=b"",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type="TIMEOUT",
            error_detail=str(exc)[:300],
        )
    except Exception as exc:  # evidence collector: isolate one target failure
        return FetchResult(
            http_status=None,
            body=b"",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type="UNEXPECTED_FETCH_ERROR",
            error_detail=f"{type(exc).__name__}: {exc}"[:300],
        )


def jsonish_string(text: str, keys: Iterable[str]) -> str | None:
    for key in keys:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw.replace("\\u0026", "&").replace("\\/", "/")
    return None


def extract_unix_time(text: str) -> str | None:
    patterns = (
        re.compile(r'"start_time"\s*:\s*"?(\d{10,13})"?', re.IGNORECASE),
        re.compile(r'"startTime"\s*:\s*"?(\d{10,13})"?', re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        value = int(match.group(1))
        if value > 10_000_000_000:
            value //= 1000
        try:
            return datetime.fromtimestamp(value, TZ_UTC8).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return None
    return None


def classify_html(text: str) -> tuple[str, float, list[str], str | None]:
    lowered = text.lower()
    for marker in RISK_MARKERS:
        if marker.lower() in lowered:
            return "UNKNOWN", 0.0, [f"risk_marker:{marker}"], "RISK_CONTROL_OR_UNAVAILABLE"

    offline = OFFLINE_VISIBLE_RE.search(text)
    if offline:
        return "OFFLINE", 0.90, [f"explicit_offline:{offline.group(1)}"], None

    live_signals = [name for name, pattern in LIVE_SIGNAL_PATTERNS if pattern.search(text)]
    if len(live_signals) >= 2:
        return "LIVE", 0.80, [f"live_signal:{name}" for name in live_signals], None

    return "UNKNOWN", 0.10, ["http_200_but_no_decisive_state_signal"], "AMBIGUOUS_PAGE"


def expectation_result(expected: str, status: str) -> bool | None:
    expected = (expected or "ANY").upper()
    if expected == "ANY":
        return None
    return expected == status


def observation_for_invalid_target(target: dict[str, Any]) -> Observation:
    rid = str(target.get("web_rid", ""))
    room_url = str(target.get("room_url") or f"https://live.douyin.com/{rid}")
    expected = str(target.get("expected", "ANY")).upper()
    status = "UNKNOWN"
    return Observation(
        schema_version=1,
        target_id=str(target.get("id", "UNKNOWN")),
        target_kind=str(target.get("kind", "UNKNOWN")),
        label=str(target.get("label", rid)),
        platform="douyin",
        web_rid=rid,
        status=status,
        creator_name=None,
        title=None,
        room_id=None,
        room_url=room_url,
        source_started_at=None,
        observed_at=now_iso(),
        source_type=SOURCE_TYPE,
        source_provider=SOURCE_PROVIDER,
        confidence=0.0,
        http_status=None,
        latency_ms=0,
        error_type="INVALID_TARGET",
        error_detail="web_rid must be 5-20 decimal digits",
        evidence=["local_validation_failed"],
        response_sha256=None,
        response_bytes=0,
        expected=expected,
        expectation_met=expectation_result(expected, status),
    )


def probe_target(target: dict[str, Any], timeout: float) -> Observation:
    rid = str(target.get("web_rid", ""))
    if not valid_web_rid(rid):
        return observation_for_invalid_target(target)

    room_url = str(target.get("room_url") or f"https://live.douyin.com/{rid}")
    expected = str(target.get("expected", "ANY")).upper()
    fetched = fetch_room(room_url, timeout=timeout)
    digest = hashlib.sha256(fetched.body).hexdigest() if fetched.body else None

    if fetched.error_type:
        status = "UNKNOWN"
        evidence = [f"fetch_error:{fetched.error_type}"]
        confidence = 0.0
        parse_error = fetched.error_type
        text = fetched.body.decode("utf-8", errors="ignore") if fetched.body else ""
    else:
        text = fetched.body.decode("utf-8", errors="ignore")
        status, confidence, evidence, parse_error = classify_html(text)

    creator_name = jsonish_string(text, ("nickname", "anchor_name")) if text else None
    title = jsonish_string(text, ("title", "room_title")) if text else None
    room_id = jsonish_string(text, ("roomId", "room_id")) if text else None
    source_started_at = extract_unix_time(text) if text else None

    error_type = fetched.error_type or parse_error
    error_detail = fetched.error_detail
    if parse_error and not error_detail:
        error_detail = parse_error

    return Observation(
        schema_version=1,
        target_id=str(target.get("id", "UNKNOWN")),
        target_kind=str(target.get("kind", "UNKNOWN")),
        label=str(target.get("label", rid)),
        platform="douyin",
        web_rid=rid,
        status=status,
        creator_name=creator_name,
        title=title,
        room_id=room_id,
        room_url=room_url,
        source_started_at=source_started_at,
        observed_at=now_iso(),
        source_type=SOURCE_TYPE,
        source_provider=SOURCE_PROVIDER,
        confidence=confidence,
        http_status=fetched.http_status,
        latency_ms=fetched.latency_ms,
        error_type=error_type,
        error_detail=error_detail,
        evidence=evidence,
        response_sha256=digest,
        response_bytes=len(fetched.body),
        expected=expected,
        expectation_met=expectation_result(expected, status),
    )


def load_targets(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError("targets.json must contain a 'targets' array")
    return [dict(item) for item in targets]


def parse_ad_hoc_rooms(values: list[str]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        if "=" in value:
            label, rid = value.split("=", 1)
        else:
            label, rid = value, value
        rid = rid.strip()
        targets.append(
            {
                "id": f"DY-ADHOC-{index:03d}",
                "label": label.strip() or rid,
                "web_rid": rid,
                "room_url": f"https://live.douyin.com/{rid}",
                "kind": "AD_HOC_CONTROL",
                "expected": "ANY",
            }
        )
    return targets


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Stage Letter Gate 0A Douyin public-web probe")
    parser.add_argument("--targets", type=Path, default=here / "targets.json")
    parser.add_argument("--output", type=Path, default=here / "data" / "smoke.jsonl")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument(
        "--room",
        action="append",
        default=[],
        metavar="LABEL=WEB_RID",
        help="append an ad-hoc room to the configured targets; repeatable",
    )
    args = parser.parse_args()

    try:
        targets = load_targets(args.targets)
    except Exception as exc:
        print(f"target configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    targets.extend(parse_ad_hoc_rooms(args.room))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    observations: list[Observation] = []
    for target in targets:
        observation = probe_target(target, timeout=args.timeout)
        observations.append(observation)
        line = json.dumps(asdict(observation), ensure_ascii=False, separators=(",", ":"))
        print(line)
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    counts = {state: sum(item.status == state for item in observations) for state in ("LIVE", "OFFLINE", "UNKNOWN")}
    failed_expectations = [item.target_id for item in observations if item.expectation_met is False]
    summary = {
        "observed_at": now_iso(),
        "total": len(observations),
        "states": counts,
        "failed_expectations": failed_expectations,
        "output": str(args.output),
        "production_approved": False,
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 1 if failed_expectations else 0


if __name__ == "__main__":
    raise SystemExit(main())
