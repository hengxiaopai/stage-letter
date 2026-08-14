#!/usr/bin/env python3
"""Stage Letter V0.1 — Gate 0A third-party provider probe.

This collector is intentionally conservative and evidence-only.
It does not approve a provider for production use and it never treats an
unexplained provider failure as OFFLINE.

Current provider: FFAPI_CN (publicly documented, authorization unverified).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TZ_UTC8 = timezone(timedelta(hours=8))
USER_AGENT = "StageLetter-Gate0A/0.1 (+https://github.com/hengxiaopai/stage-letter)"
SOURCE_TYPE = "THIRD_PARTY_PUBLIC_API"
SOURCE_PROVIDER = "FFAPI_CN"
AUTHORIZATION_BASIS = "PUBLIC_DOCS_ONLY_UNVERIFIED"
ENDPOINT = "https://ffapi.cn/int/v1/douyinlive"

EXPLICIT_OFFLINE_MARKERS = (
    "未开播",
    "直播结束",
    "已下播",
    "没有直播",
    "无直播",
    "not live",
    "offline",
)


@dataclass(frozen=True)
class Observation:
    schema_version: int
    target_id: str
    label: str
    web_rid: str
    status: str
    title: str | None
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


def valid_web_rid(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,20}", value or ""))


def load_targets(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError("provider_targets.json must contain a 'targets' array")
    return [dict(item) for item in targets]


def fetch_json(web_rid: str, timeout: float) -> tuple[int | None, bytes, int, str | None]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"id": web_rid, "type": "hls"})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
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
        return int(exc.code), body, round((time.perf_counter() - started) * 1000), f"HTTP_{exc.code}"
    except urllib.error.URLError as exc:
        return None, b"", round((time.perf_counter() - started) * 1000), f"NETWORK:{getattr(exc, 'reason', exc)}"
    except TimeoutError:
        return None, b"", round((time.perf_counter() - started) * 1000), "TIMEOUT"
    except Exception as exc:
        return None, b"", round((time.perf_counter() - started) * 1000), f"UNEXPECTED:{type(exc).__name__}"


def count_stream_urls(payload: dict[str, Any]) -> int:
    urls = payload.get("urls")
    if isinstance(urls, dict):
        return sum(
            1
            for value in urls.values()
            if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://") or value.startswith("//"))
        )
    if isinstance(urls, list):
        return sum(
            1
            for value in urls
            if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://") or value.startswith("//"))
        )
    return 0


def classify(payload: dict[str, Any]) -> tuple[str, float, list[str], str | None]:
    code = payload.get("code")
    message = str(payload.get("msg") or payload.get("message") or "")
    stream_url_count = count_stream_urls(payload)

    if str(code) == "200" and stream_url_count > 0:
        return "LIVE", 0.90, [f"provider_code:{code}", f"stream_urls:{stream_url_count}"], None

    lowered = message.lower()
    for marker in EXPLICIT_OFFLINE_MARKERS:
        if marker.lower() in lowered:
            return "OFFLINE", 0.80, [f"explicit_provider_offline:{marker}"], None

    return "UNKNOWN", 0.0, [f"provider_code:{code}", "no_decisive_live_or_offline_evidence"], "PROVIDER_AMBIGUOUS"


def probe_target(target: dict[str, Any], timeout: float) -> Observation:
    target_id = str(target.get("id", "UNKNOWN"))
    label = str(target.get("label", ""))
    web_rid = str(target.get("web_rid", ""))

    if not valid_web_rid(web_rid):
        return Observation(
            schema_version=1,
            target_id=target_id,
            label=label,
            web_rid=web_rid,
            status="UNKNOWN",
            title=None,
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

    http_status, body, latency_ms, fetch_error = fetch_json(web_rid, timeout)
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
    else:
        status, confidence, evidence, error_type = classify(payload)

    # Metadata is trusted only for decisive LIVE observations.
    title = str(payload.get("title")) if status == "LIVE" and payload.get("title") else None
    stream_url_count = count_stream_urls(payload) if status == "LIVE" else 0
    provider_message = payload.get("msg") or payload.get("message")
    provider_code = payload.get("code")

    return Observation(
        schema_version=1,
        target_id=target_id,
        label=label,
        web_rid=web_rid,
        status=status,
        title=title,
        stream_url_count=stream_url_count,
        observed_at=now_iso(),
        source_type=SOURCE_TYPE,
        source_provider=SOURCE_PROVIDER,
        authorization_basis=AUTHORIZATION_BASIS,
        production_approved=False,
        confidence=confidence,
        http_status=http_status,
        latency_ms=latency_ms,
        provider_code=provider_code,
        provider_message=str(provider_message)[:200] if provider_message is not None else None,
        error_type=error_type,
        evidence=evidence,
        response_sha256=digest,
        response_bytes=len(body),
    )


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Stage Letter Gate 0A third-party provider probe")
    parser.add_argument("--targets", type=Path, default=here / "provider_targets.json")
    parser.add_argument("--output", type=Path, default=here / "data" / "provider-smoke.jsonl")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    try:
        targets = load_targets(args.targets)
    except Exception as exc:
        print(f"target configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    observations: list[Observation] = []
    with args.output.open("w", encoding="utf-8") as handle:
        for target in targets:
            obs = probe_target(target, args.timeout)
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
        "total": len(observations),
        "states": counts,
        "decisive_live_found": counts["LIVE"] > 0,
        "output": str(args.output),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
