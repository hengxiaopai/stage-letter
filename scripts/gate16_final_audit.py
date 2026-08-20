#!/usr/bin/env python3
"""Gate 1.6-5 final read-only closure audit.

Checks the persisted evidence after the one real WeChat acceptance. This probe
never calls WeChat and never writes the database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings

EXPECTED_HEAD = "a63f4b2d9e71"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-user-id", required=True, type=int)
    parser.add_argument("--fallback-user-id", required=True, type=int)
    parser.add_argument("--event-id", required=True)
    return parser


async def _main(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            real_user = (
                await connection.execute(
                    text("SELECT openid FROM users WHERE id=:user_id"),
                    {"user_id": args.real_user_id},
                )
            ).mappings().one_or_none()
            grant = (
                await connection.execute(
                    text(
                        "SELECT granted_count, consumed_count FROM wechat_subscription_grants "
                        "WHERE user_id=:user_id AND template_id=:template_id"
                    ),
                    {
                        "user_id": args.real_user_id,
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()
            delivery = (
                await connection.execute(
                    text(
                        "SELECT nd.state, nd.attempt, nd.sent_at "
                        "FROM notification_deliveries nd "
                        "JOIN live_events le ON le.id=nd.live_event_id "
                        "WHERE nd.user_id=:user_id "
                        "AND le.event_id=:event_id "
                        "AND nd.channel='WECHAT_SUBSCRIBE'"
                    ),
                    {"user_id": args.real_user_id, "event_id": args.event_id},
                )
            ).mappings().one_or_none()
            old_ambiguous_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM notification_deliveries "
                        "WHERE user_id=:user_id AND state='AMBIGUOUS'"
                    ),
                    {"user_id": args.fallback_user_id},
                )
                or 0
            )

        requirements_text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        tzdata_declared = any(
            line.strip().lower().startswith("tzdata")
            for line in requirements_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

        openid = str(real_user["openid"]) if real_user is not None else ""
        granted = int(grant["granted_count"]) if grant is not None else 0
        consumed = int(grant["consumed_count"]) if grant is not None else 0
        available = max(0, granted - consumed)
        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "real_user_exists": real_user is not None,
            "real_user_not_debug_fallback": bool(openid) and not openid.startswith("dev_"),
            "grant_consumed_once": grant is not None and granted == 1 and consumed == 1,
            "grant_available_zero": available == 0,
            "accepted_delivery_sent": delivery is not None and delivery["state"] == "SENT",
            "accepted_delivery_has_sent_at": delivery is not None and delivery["sent_at"] is not None,
            "old_ambiguous_delivery_preserved": old_ambiguous_count >= 1,
            "tzdata_declared": tzdata_declared,
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "gate": "1.6-5",
                    "probe": "final_closure_audit",
                    "status": "PASS" if passed else "FAIL",
                    "migration_head": head,
                    "real_user_id": str(args.real_user_id),
                    "real_openid_kind": (
                        "REAL_OR_EXTERNAL" if openid and not openid.startswith("dev_") else "INVALID"
                    ),
                    "real_openid_tail": openid[-4:] if openid else None,
                    "accepted_event_id": args.event_id,
                    "accepted_delivery_state": delivery["state"] if delivery is not None else None,
                    "accepted_delivery_attempt": int(delivery["attempt"]) if delivery is not None else None,
                    "grant_granted": granted,
                    "grant_consumed": consumed,
                    "grant_available": available,
                    "fallback_user_id": str(args.fallback_user_id),
                    "old_ambiguous_delivery_count": old_ambiguous_count,
                    "tzdata_declared": tzdata_declared,
                    "checks": checks,
                    "real_wechat_called": False,
                    "database_write_performed": False,
                    "old_ambiguous_delivery_replayed": False,
                    "worker_exactly_once_claimed": False,
                    "provider_exactly_once_claimed": False,
                    "notification_exactly_once_claimed": False,
                    "production_approved": passed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if passed else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
