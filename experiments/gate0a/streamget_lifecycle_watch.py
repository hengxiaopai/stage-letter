#!/usr/bin/env python3
"""Stage Letter Gate 0A — capture a real OFFLINE -> LIVE -> OFFLINE lifecycle.

This watcher deliberately reuses streamget_status_probe.py as the single
normalization authority. Every probe result is appended to JSONL. UNKNOWN
observations are logged but never advance or close the lifecycle.

Expected Gate sequence:
    OFFLINE(status=4) -> LIVE(status=2) -> OFFLINE(status=4)

Usage:
    python experiments/gate0a/streamget_lifecycle_watch.py \
      "https://www.douyin.com/user/<sec_uid>" \
      --interval 60

Security:
- DOUYIN_COOKIE is optional and inherited from the process environment.
- Cookie contents are never printed or persisted by this watcher.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TZ_UTC8 = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ_UTC8).isoformat(timespec="seconds")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def probe_script() -> Path:
    return Path(__file__).resolve().with_name("streamget_status_probe.py")


def default_output(profile_url: str) -> Path:
    sec_tail = profile_url.rstrip("/").split("/")[-1].split("?", 1)[0]
    safe_tail = "".join(ch for ch in sec_tail if ch.isalnum() or ch in "-_" )[-24:] or "profile"
    stamp = datetime.now(TZ_UTC8).strftime("%Y%m%d-%H%M%S")
    return repo_root() / "experiments" / "gate0a" / "data" / f"lifecycle-{safe_tail}-{stamp}.jsonl"


def run_probe(profile_url: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(probe_script()), profile_url],
        cwd=repo_root(),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stdout = proc.stdout.strip()
    if not stdout:
        return {
            "ok": False,
            "platform": "douyin",
            "url": profile_url,
            "input_mode": "PROFILE",
            "status": "UNKNOWN",
            "raw_room_status": None,
            "observed_at": now_iso(),
            "error_type": "WATCHER_EMPTY_PROBE_OUTPUT",
            "probe_exit_code": proc.returncode,
        }

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "platform": "douyin",
            "url": profile_url,
            "input_mode": "PROFILE",
            "status": "UNKNOWN",
            "raw_room_status": None,
            "observed_at": now_iso(),
            "error_type": "WATCHER_PROBE_OUTPUT_PARSE_ERROR",
            "probe_exit_code": proc.returncode,
        }

    result["probe_exit_code"] = proc.returncode
    return result


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_url", help="Stable Douyin profile/sec_uid URL")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds (default: 60)")
    parser.add_argument("--output", help="JSONL output path; defaults under experiments/gate0a/data/")
    args = parser.parse_args()

    if not args.profile_url.startswith("https://www.douyin.com/user/"):
        print("Gate lifecycle watcher requires a PROFILE/sec_uid URL.", file=sys.stderr)
        return 2
    if args.interval < 15:
        print("Refusing intervals below 15 seconds for this Gate watcher.", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else default_output(args.profile_url)

    phase = "WAIT_INITIAL_OFFLINE"
    sample_no = 0
    initial_offline_at: str | None = None
    live_at: str | None = None
    final_offline_at: str | None = None
    anchor_name: str | None = None

    print(f"Gate 0A lifecycle watcher started: {now_iso()}")
    print(f"Profile: {args.profile_url}")
    print(f"Interval: {args.interval}s")
    print(f"Evidence: {output}")
    print("Target: OFFLINE -> LIVE -> OFFLINE. UNKNOWN never advances the lifecycle.")

    try:
        while True:
            sample_no += 1
            result = run_probe(args.profile_url)
            status = str(result.get("status") or "UNKNOWN")
            observed_at = str(result.get("observed_at") or now_iso())
            anchor_name = result.get("anchor_name") or anchor_name
            event = None

            if phase == "WAIT_INITIAL_OFFLINE" and status == "OFFLINE":
                initial_offline_at = observed_at
                phase = "WAIT_LIVE"
                event = "INITIAL_OFFLINE_CAPTURED"
            elif phase == "WAIT_LIVE" and status == "LIVE":
                live_at = observed_at
                phase = "WAIT_FINAL_OFFLINE"
                event = "LIVE_TRANSITION_CAPTURED"
            elif phase == "WAIT_FINAL_OFFLINE" and status == "OFFLINE":
                final_offline_at = observed_at
                phase = "COMPLETE"
                event = "FINAL_OFFLINE_CAPTURED"

            row = {
                "watcher_sample": sample_no,
                "watcher_phase": phase,
                "watcher_event": event,
                **result,
            }
            append_jsonl(output, row)

            raw = result.get("raw_room_status")
            error_type = result.get("error_type")
            print(
                f"[{observed_at}] #{sample_no} status={status} raw={raw} "
                f"phase={phase} event={event or '-'} error={error_type or '-'}"
            )

            if phase == "COMPLETE":
                summary = {
                    "gate": "0A",
                    "result": "PASS",
                    "sequence": ["OFFLINE", "LIVE", "OFFLINE"],
                    "profile_url": args.profile_url,
                    "anchor_name": anchor_name,
                    "initial_offline_at": initial_offline_at,
                    "live_at": live_at,
                    "final_offline_at": final_offline_at,
                    "samples": sample_no,
                    "evidence_file": str(output),
                }
                append_jsonl(output, {"watcher_summary": summary})
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 0

            time.sleep(args.interval)

    except KeyboardInterrupt:
        summary = {
            "gate": "0A",
            "result": "INCOMPLETE",
            "profile_url": args.profile_url,
            "anchor_name": anchor_name,
            "phase": phase,
            "initial_offline_at": initial_offline_at,
            "live_at": live_at,
            "final_offline_at": final_offline_at,
            "samples": sample_no,
            "evidence_file": str(output),
            "stopped_at": now_iso(),
        }
        append_jsonl(output, {"watcher_summary": summary})
        print()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
