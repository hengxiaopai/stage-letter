#!/usr/bin/env python3
"""Gate 4.5 compatibility runner for one controlled real-device notification.

Gate 1.6's historical acceptance scripts deliberately retain their original
migration-head contract.  Gate 4.5 reuses their isolated fixture and atomic
send path, but explicitly binds the run to the current Gate 4 migration head.
The prepared disabled account and accepted delivery are durable acceptance
evidence; they are not production monitoring data and are not cleaned up.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import gate16_prepare_real_wechat_event as prepare
from scripts import gate16_real_wechat_acceptance as acceptance


EXPECTED_HEAD = "e34d7a2c1b50"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)

    prepare_command = command.add_parser("prepare")
    prepare_command.add_argument("--user-id", required=True)

    send_command = command.add_parser("send")
    send_command.add_argument("--user-id", required=True)
    send_command.add_argument("--event-id", required=True)
    send_command.add_argument("--room-title", default="开场信 Gate 4.5 真机通知验收")
    send_command.add_argument("--send", action="store_true", required=True)
    return parser


async def _main(args: argparse.Namespace) -> int:
    # Keep the old Gate 1.6 proof frozen while giving Gate 4.5 its own explicit
    # schema binding.  Both delegated scripts still perform the head check.
    prepare.EXPECTED_HEAD = EXPECTED_HEAD
    acceptance.EXPECTED_HEAD = EXPECTED_HEAD

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        if args.command == "prepare":
            exit_code = await prepare._main(argparse.Namespace(user_id=args.user_id))
        else:
            exit_code = await acceptance._main(
                argparse.Namespace(
                    user_id=args.user_id,
                    event_id=args.event_id,
                    room_title=args.room_title,
                    send=args.send,
                    miniprogram_state="developer",
                )
            )

    payload = json.loads(output.getvalue())
    payload["gate"] = "4.5"
    # Provider acceptance proves provider acceptance only.  Device receipt,
    # user click, and an independent production-release decision remain out of
    # scope for this controlled developer acceptance.
    payload["production_approved"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
