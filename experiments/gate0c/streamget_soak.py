#!/usr/bin/env python3
"""Gate 0C-3 real StreamGet soak / network-fault evidence harness.

The harness reuses Gate 0A's in-process ``streamget_status_probe.probe`` to
avoid the Windows subprocess/stdout transport issue found during the lifecycle
watcher experiment. It writes normalized JSONL evidence only; no raw provider
payload or cookie value is recorded.

Network fault injection temporarily points standard proxy environment variables
to 127.0.0.1:1 for selected rounds. If StreamGet ignores those variables and a
decisive result still returns, the injection is recorded as *ineffective* / an
inconclusive fault injection rather than being mislabeled as a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

GATE0A_DIR = Path(__file__).resolve().parents[1] / "gate0a"
if str(GATE0A_DIR) not in sys.path:
    sys.path.insert(0, str(GATE0A_DIR))

from streamget_status_probe import probe as streamget_probe  # noqa: E402

from platform_health import (  # noqa: E402
    CanonicalStatus,
    FailureKind,
    HealthTracker,
    ProbeSample,
)
from poll_policy import PollContext, decide_poll  # noqa: E402


TZ_UTC8 = timezone(timedelta(hours=8))
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def now() -> datetime:
    return datetime.now(TZ_UTC8)


def parse_rounds(value: str) -> set[int]:
    if not value.strip():
        return set()
    rounds: set[int] = set()
    for part in value.split(","):
        number = int(part.strip())
        if number < 1:
            raise argparse.ArgumentTypeError("fault rounds must be >= 1")
        rounds.add(number)
    return rounds


@contextmanager
def injected_dead_proxy(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    old = {key: os.environ.get(key) for key in PROXY_KEYS}
    try:
        for key in PROXY_KEYS:
            os.environ[key] = "http://127.0.0.1:1"
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def normalized_status(value: Any) -> CanonicalStatus:
    try:
        return CanonicalStatus(str(value))
    except ValueError:
        return CanonicalStatus.UNKNOWN


def classify_failure(
    result: dict[str, Any],
    *,
    injection_requested: bool,
) -> FailureKind | None:
    status = normalized_status(result.get("status"))
    if status in (CanonicalStatus.LIVE, CanonicalStatus.OFFLINE):
        return None

    error_type = str(result.get("error_type") or "").upper()
    if injection_requested and error_type == "STREAMGET_REQUEST_OR_PARSE_ERROR":
        return FailureKind.NETWORK
    if "429" in error_type or "RATE" in error_type:
        return FailureKind.RATE_LIMIT
    if "AUTH" in error_type:
        return FailureKind.AUTH
    if "BLOCK" in error_type or "CHALLENGE" in error_type:
        return FailureKind.BLOCKED
    if "PARSE" in error_type or "ROOM_STATUS" in error_type or "INVALID" in error_type:
        return FailureKind.PARSE
    if "NETWORK" in error_type or "CONNECT" in error_type or "TIMEOUT" in error_type:
        return FailureKind.NETWORK
    if not error_type:
        return FailureKind.EMPTY
    return FailureKind.OTHER


def deterministic_jitter_unit(target: str, round_number: int) -> float:
    digest = hashlib.sha256(f"{target}|{round_number}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / float((1 << 64) - 1)
    return value * 2.0 - 1.0


def default_output_path() -> Path:
    stamp = now().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "data" / f"streamget-soak-{stamp}.jsonl"


async def run(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    trackers = {target: HealthTracker() for target in args.profiles}
    summaries: dict[str, dict[str, Any]] = {
        target: {
            "samples": 0,
            "live": 0,
            "offline": 0,
            "unknown": 0,
            "injection_requested": 0,
            "injection_effective": 0,
            "false_offline_from_failure": 0,
        }
        for target in args.profiles
    }

    print(f"Gate 0C-3 StreamGet soak started: {now().isoformat(timespec='seconds')}")
    print(f"Rounds: {args.rounds}; interval: {args.interval}s")
    print(f"Fault rounds: {sorted(args.inject_network_failure_rounds)}")
    print(f"Evidence: {output}")

    with output.open("a", encoding="utf-8") as handle:
        for round_number in range(1, args.rounds + 1):
            inject = round_number in args.inject_network_failure_rounds

            for target in args.profiles:
                started = now()
                monotonic_start = time.perf_counter()
                with injected_dead_proxy(inject):
                    result = await streamget_probe(target)
                completed = now()
                latency_ms = max(0, round((time.perf_counter() - monotonic_start) * 1000))

                status = normalized_status(result.get("status"))
                failure_kind = classify_failure(result, injection_requested=inject)
                injection_effective = inject and status is CanonicalStatus.UNKNOWN and failure_kind is not None

                sample = ProbeSample(
                    sample_id=f"{round_number}:{hashlib.sha256(target.encode('utf-8')).hexdigest()[:16]}",
                    started_at=started,
                    completed_at=completed,
                    status=status,
                    latency_ms=latency_ms,
                    failure_kind=failure_kind,
                    source="STREAMGET_PROFILE_SOAK",
                )
                tracker = trackers[target]
                health_result = tracker.process(sample)
                snapshot = tracker.snapshot()
                poll = decide_poll(
                    PollContext(
                        health_state=snapshot.state,
                        failure_kind=failure_kind,
                        consecutive_failures=snapshot.consecutive_failures,
                        jitter_unit=deterministic_jitter_unit(target, round_number),
                    )
                )

                summary = summaries[target]
                summary["samples"] += 1
                summary[status.value.lower()] += 1
                if inject:
                    summary["injection_requested"] += 1
                if injection_effective:
                    summary["injection_effective"] += 1
                if failure_kind is not None and status is CanonicalStatus.OFFLINE:
                    summary["false_offline_from_failure"] += 1

                record = {
                    "round": round_number,
                    "profile_url": target,
                    "anchor_name": result.get("anchor_name"),
                    "status": status.value,
                    "raw_room_status": result.get("raw_room_status"),
                    "error_type": result.get("error_type"),
                    "failure_kind": failure_kind.value if failure_kind else None,
                    "latency_ms": latency_ms,
                    "started_at": started.isoformat(timespec="seconds"),
                    "completed_at": completed.isoformat(timespec="seconds"),
                    "health_before": health_result.previous_state.value,
                    "health_after": health_result.current_state.value,
                    "consecutive_failures": snapshot.consecutive_failures,
                    "poll_delay_s": poll.delay_s,
                    "poll_mode": poll.mode.value,
                    "injection_requested": inject,
                    "injection_effective": injection_effective,
                    "cookie_configured": bool(result.get("cookie_configured")),
                    "production_approved": False,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()

                print(
                    f"round={round_number} status={status.value} raw={result.get('raw_room_status')} "
                    f"health={health_result.current_state.value} failures={snapshot.consecutive_failures} "
                    f"latency={latency_ms}ms inject={inject}/{injection_effective} "
                    f"next={poll.delay_s}s anchor={result.get('anchor_name') or '-'}"
                )

            if round_number < args.rounds and args.interval > 0:
                await asyncio.sleep(args.interval)

    final = {
        "gate": "0C-3",
        "result": "EVIDENCE_CAPTURED",
        "evidence_file": str(output),
        "profiles": [],
    }
    for target in args.profiles:
        item = dict(summaries[target])
        item["profile_url"] = target
        item["final_health"] = trackers[target].state.value
        item["fault_injection_conclusive"] = (
            item["injection_requested"] == 0 or item["injection_effective"] > 0
        )
        final["profiles"].append(item)

    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate 0C-3 real StreamGet soak harness")
    parser.add_argument("profiles", nargs="+", help="Douyin profile/sec_uid URLs")
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument(
        "--inject-network-failure-rounds",
        type=parse_rounds,
        default=set(),
        metavar="2,3,4,5",
    )
    parser.add_argument("--output")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    if args.interval < 0:
        parser.error("--interval must be >= 0")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
