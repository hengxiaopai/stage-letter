#!/usr/bin/env python3
"""Gate 1.3-3 provider-backed probe for the formal Douyin adapter.

The probe exercises the production-facing formal chain only:

    StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot

It does not import legacy platform_adapters or Gate 0 experiments. Optional
DOUYIN_COOKIE is read from the environment but never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.platforms.douyin import DouyinFormalAdapter
from stage_letter.infrastructure.platforms.douyin_streamget import StreamGetDouyinGateway
from stage_letter.infrastructure.platforms.failures import ProviderOperationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exercise the formal Douyin StreamGet provider chain.",
    )
    parser.add_argument(
        "identity",
        help="Stable Douyin sec_uid or https://www.douyin.com/user/<sec_uid> URL",
    )
    parser.add_argument(
        "--expect",
        choices=("LIVE", "OFFLINE", "ANY"),
        default="ANY",
        help="Optional independently verified ground-truth expectation.",
    )
    return parser


async def _run(identity: str, expected: str) -> tuple[int, dict[str, object]]:
    cookie = os.environ.get("DOUYIN_COOKIE", "").strip() or None
    gateway = StreamGetDouyinGateway(cookie=cookie)
    adapter = DouyinFormalAdapter(gateway)

    try:
        resolved = await adapter.resolve_creator(identity)
        account = PlatformAccount(
            account_id="probe-account",
            creator_id="probe-creator",
            platform="douyin",
            platform_user_id=resolved.platform_user_id,
            room_id=resolved.room_id,
            canonical_url=resolved.canonical_url,
        )
        profile = await adapter.get_creator_profile(account)
        snapshot = await adapter.get_live_snapshot(account)
    except ProviderOperationError as exc:
        result = {
            "gate": "1.3-3",
            "platform": "douyin",
            "status": "UNKNOWN",
            "provider_failure_kind": exc.failure.kind.value,
            "provider_source": exc.failure.source,
            "cookie_configured": bool(cookie),
            "gate0a_status": "DEGRADED",
            "production_approved": False,
        }
        return 2, result
    except Exception as exc:
        result = {
            "gate": "1.3-3",
            "platform": "douyin",
            "status": "UNKNOWN",
            "unexpected_error": type(exc).__name__,
            "cookie_configured": bool(cookie),
            "gate0a_status": "DEGRADED",
            "production_approved": False,
        }
        return 2, result

    status = snapshot.status.value
    result = {
        "gate": "1.3-3",
        "platform": snapshot.platform,
        "platform_user_id": snapshot.platform_user_id,
        "display_name": profile.display_name,
        "status": status,
        "observed_at": snapshot.observed_at.isoformat(),
        "source": snapshot.source,
        "room_id": snapshot.room_id,
        "canonical_url": snapshot.canonical_url,
        "title": snapshot.title,
        "source_started_at": (
            snapshot.source_started_at.isoformat() if snapshot.source_started_at else None
        ),
        "cookie_configured": bool(cookie),
        "gate0a_status": "DEGRADED",
        "production_approved": False,
    }

    if expected != "ANY" and status != expected:
        result["expectation"] = expected
        result["expectation_match"] = False
        return 3, result

    result["expectation"] = expected
    result["expectation_match"] = expected == "ANY" or status == expected
    if status not in ("LIVE", "OFFLINE"):
        return 4, result
    return 0, result


def main() -> int:
    args = _parser().parse_args()
    code, result = asyncio.run(_run(args.identity, args.expect))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
