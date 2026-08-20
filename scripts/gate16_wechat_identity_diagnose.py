#!/usr/bin/env python3
"""Gate 1.6-5 read-only WeChat recipient identity diagnosis.

The probe never calls WeChat, never writes the database, and never prints the
full openid. It is intended to distinguish a real Mini Program openid from the
DEBUG fallback ``dev_<hash>`` identity before another real send is attempted.
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="formal numeric user id")
    return parser


async def _main(args: argparse.Namespace) -> int:
    if not str(args.user_id).isdigit():
        print(json.dumps({
            "gate": "1.6-5",
            "probe": "wechat_identity_diagnose",
            "status": "BLOCKED",
            "reason": "--user-id must be numeric",
            "real_wechat_called": False,
            "database_write_performed": False,
        }, indent=2))
        return 2

    user_id = int(args.user_id)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            user = (
                await connection.execute(
                    text("SELECT openid FROM users WHERE id=:user_id"),
                    {"user_id": user_id},
                )
            ).mappings().one_or_none()
            grant = (
                await connection.execute(
                    text(
                        "SELECT granted_count, consumed_count "
                        "FROM wechat_subscription_grants "
                        "WHERE user_id=:user_id AND template_id=:template_id"
                    ),
                    {
                        "user_id": user_id,
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()

        if user is None:
            payload = {
                "gate": "1.6-5",
                "probe": "wechat_identity_diagnose",
                "status": "BLOCKED",
                "reason": "user not found",
                "user_id": str(user_id),
                "real_wechat_called": False,
                "database_write_performed": False,
                "production_approved": False,
            }
            print(json.dumps(payload, indent=2))
            return 2

        openid = str(user["openid"])
        is_dev_fallback = openid.startswith("dev_")
        granted = int(grant["granted_count"]) if grant is not None else 0
        consumed = int(grant["consumed_count"]) if grant is not None else 0
        available = max(0, granted - consumed)
        status = "BLOCKED" if is_dev_fallback else "PASS"
        reason = (
            "user openid is DEBUG fallback and is invalid for real WeChat send"
            if is_dev_fallback
            else "user openid is not a DEBUG fallback"
        )
        print(json.dumps({
            "gate": "1.6-5",
            "probe": "wechat_identity_diagnose",
            "status": status,
            "reason": reason,
            "user_id": str(user_id),
            "openid_kind": "DEV_FALLBACK" if is_dev_fallback else "REAL_OR_EXTERNAL",
            "openid_tail": openid[-4:] if openid else None,
            "template_id": settings.wx_template_live_start,
            "grant_granted": granted,
            "grant_consumed": consumed,
            "grant_available": available,
            "safe_to_attempt_real_send": not is_dev_fallback and available > 0,
            "real_wechat_called": False,
            "database_write_performed": False,
            "provider_exactly_once_claimed": False,
            "notification_exactly_once_claimed": False,
            "production_approved": False,
        }, ensure_ascii=False, indent=2))
        return 0 if status == "PASS" else 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
