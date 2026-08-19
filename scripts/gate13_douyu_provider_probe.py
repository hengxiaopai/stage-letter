#!/usr/bin/env python3
"""Provider-backed probe for Gate 1.3-4C Douyu formal adapter."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.platforms.douyu import DouyuFormalAdapter
from stage_letter.infrastructure.platforms.douyu_http import DouyuHttpGateway
from stage_letter.infrastructure.platforms.failures import ProviderOperationError


_MARKDOWN_LINK_RE = re.compile(r"^\[(https?://[^\]]+)\]\((https?://[^)]+)\)$")


def _normalize_identity(value: str) -> tuple[str, bool]:
    text = value.strip()
    match = _MARKDOWN_LINK_RE.fullmatch(text)
    if match is None:
        return text, False
    visible, target = match.groups()
    if visible != target:
        raise ValueError("markdown link label and target differ")
    return target, True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise the formal Douyu provider chain.")
    parser.add_argument("identity", help="Douyu room id or room URL")
    parser.add_argument(
        "--expect",
        choices=("LIVE", "OFFLINE", "ANY"),
        default="ANY",
        help="Independently verified current state expectation.",
    )
    return parser


async def _run(identity: str, expected: str) -> tuple[int, dict[str, object]]:
    try:
        normalized, input_normalized = _normalize_identity(identity)
    except ValueError as exc:
        return 2, {
            "gate": "1.3-4C",
            "platform": "douyu",
            "status": "UNKNOWN",
            "provider_failure_kind": "UNKNOWN",
            "provider_source": "probe.input",
            "provider_failure_detail": str(exc),
            "expectation": expected,
            "expectation_match": False,
            "input_normalized": False,
            "production_approved": False,
        }

    gateway = DouyuHttpGateway()
    adapter = DouyuFormalAdapter(gateway)
    try:
        resolved = await adapter.resolve_creator(normalized)
        account = PlatformAccount(
            account_id="probe-account",
            creator_id="probe-creator",
            platform="douyu",
            platform_user_id=resolved.platform_user_id,
            room_id=resolved.room_id,
            canonical_url=resolved.canonical_url,
        )
        snapshot = await adapter.get_live_snapshot(account)
    except ProviderOperationError as exc:
        return 2, {
            "gate": "1.3-4C",
            "platform": "douyu",
            "status": "UNKNOWN",
            "provider_failure_kind": exc.failure.kind.value,
            "provider_source": exc.failure.source,
            "provider_failure_detail": exc.failure.detail,
            "expectation": expected,
            "expectation_match": False,
            "input_normalized": input_normalized,
            "production_approved": False,
        }
    except Exception as exc:
        return 2, {
            "gate": "1.3-4C",
            "platform": "douyu",
            "status": "UNKNOWN",
            "unexpected_error": type(exc).__name__,
            "expectation": expected,
            "expectation_match": False,
            "input_normalized": input_normalized,
            "production_approved": False,
        }

    status = snapshot.status.value
    result = {
        "gate": "1.3-4C",
        "platform": snapshot.platform,
        "platform_user_id": snapshot.platform_user_id,
        "status": status,
        "observed_at": snapshot.observed_at.isoformat(),
        "source": snapshot.source,
        "room_id": snapshot.room_id,
        "canonical_url": snapshot.canonical_url,
        "title": snapshot.title,
        "source_started_at": (
            snapshot.source_started_at.isoformat() if snapshot.source_started_at else None
        ),
        "expectation": expected,
        "expectation_match": expected == "ANY" or status == expected,
        "input_normalized": input_normalized,
        "production_approved": False,
    }
    if expected != "ANY" and status != expected:
        return 3, result
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
