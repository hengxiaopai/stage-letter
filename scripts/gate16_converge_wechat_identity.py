#!/usr/bin/env python3
"""Gate 1.6-5 controlled convergence from a DEBUG fallback user to an existing real user.

This repair moves only the positive WeChat grant ledger that was recorded against
a DEBUG fallback identity. It deliberately does NOT merge/delete users, replay
old deliveries, transfer historical deliveries, or call WeChat. The old fallback
user and its AMBIGUOUS delivery remain immutable evidence.

Default mode is read-only. Pass --apply only after reviewing READY output.
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
    parser.add_argument("--fallback-user-id", required=True, type=int)
    parser.add_argument("--real-user-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def _blocked(reason: str, **extra) -> int:
    payload = {
        "gate": "1.6-5",
        "probe": "converge_wechat_identity",
        "status": "BLOCKED",
        "reason": reason,
        "real_wechat_called": False,
        "old_ambiguous_delivery_replayed": False,
        "provider_exactly_once_claimed": False,
        "notification_exactly_once_claimed": False,
        "production_approved": False,
    }
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2


async def _snapshot(connection, fallback_user_id: int, real_user_id: int) -> dict:
    head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    users = (
        await connection.execute(
            text(
                "SELECT id, openid FROM users "
                "WHERE id IN (:fallback_user_id, :real_user_id) ORDER BY id"
            ),
            {
                "fallback_user_id": fallback_user_id,
                "real_user_id": real_user_id,
            },
        )
    ).mappings().all()
    by_id = {int(row["id"]): str(row["openid"]) for row in users}
    fallback_grant = (
        await connection.execute(
            text(
                "SELECT id, granted_count, consumed_count "
                "FROM wechat_subscription_grants "
                "WHERE user_id=:user_id AND template_id=:template_id"
            ),
            {
                "user_id": fallback_user_id,
                "template_id": settings.wx_template_live_start,
            },
        )
    ).mappings().one_or_none()
    real_grant = (
        await connection.execute(
            text(
                "SELECT id, granted_count, consumed_count "
                "FROM wechat_subscription_grants "
                "WHERE user_id=:user_id AND template_id=:template_id"
            ),
            {
                "user_id": real_user_id,
                "template_id": settings.wx_template_live_start,
            },
        )
    ).mappings().one_or_none()
    old_ambiguous_count = int(
        await connection.scalar(
            text(
                "SELECT count(*) FROM notification_deliveries "
                "WHERE user_id=:user_id AND state='AMBIGUOUS'"
            ),
            {"user_id": fallback_user_id},
        )
        or 0
    )
    return {
        "head": head,
        "fallback_openid": by_id.get(fallback_user_id),
        "real_openid": by_id.get(real_user_id),
        "fallback_grant": fallback_grant,
        "real_grant": real_grant,
        "old_ambiguous_count": old_ambiguous_count,
    }


async def _main(args: argparse.Namespace) -> int:
    if args.fallback_user_id == args.real_user_id:
        return _blocked("fallback and real user ids must differ")
    if not settings.wx_template_live_start:
        return _blocked("WX_TEMPLATE_LIVE_START not configured")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            snap = await _snapshot(connection, args.fallback_user_id, args.real_user_id)

        if snap["head"] != EXPECTED_HEAD:
            return _blocked(
                "migration head mismatch",
                expected_head=EXPECTED_HEAD,
                observed_head=snap["head"],
            )

        fallback_openid = snap["fallback_openid"]
        real_openid = snap["real_openid"]
        if fallback_openid is None:
            return _blocked("fallback user not found", fallback_user_id=str(args.fallback_user_id))
        if real_openid is None:
            return _blocked("real user not found", real_user_id=str(args.real_user_id))
        if not fallback_openid.startswith("dev_"):
            return _blocked(
                "fallback user is not a DEBUG fallback identity",
                fallback_user_id=str(args.fallback_user_id),
                fallback_openid_kind="NON_DEV",
            )
        if real_openid.startswith("dev_"):
            return _blocked(
                "target real user is also a DEBUG fallback identity",
                real_user_id=str(args.real_user_id),
            )
        if fallback_openid == real_openid:
            return _blocked("fallback and real users unexpectedly share one openid")

        fallback_grant = snap["fallback_grant"]
        real_grant = snap["real_grant"]
        if fallback_grant is None:
            return _blocked("fallback user has no grant ledger for current template")
        granted = int(fallback_grant["granted_count"])
        consumed = int(fallback_grant["consumed_count"])
        available = max(0, granted - consumed)
        if consumed != 0 or available <= 0:
            return _blocked(
                "fallback grant is not a clean unconsumed positive grant",
                fallback_granted=granted,
                fallback_consumed=consumed,
                fallback_available=available,
            )
        if real_grant is not None:
            return _blocked(
                "real user already has a grant ledger; automatic grant merge is forbidden",
                real_user_id=str(args.real_user_id),
                real_granted=int(real_grant["granted_count"]),
                real_consumed=int(real_grant["consumed_count"]),
            )

        base_payload = {
            "gate": "1.6-5",
            "probe": "converge_wechat_identity",
            "migration_head": EXPECTED_HEAD,
            "fallback_user_id": str(args.fallback_user_id),
            "real_user_id": str(args.real_user_id),
            "fallback_openid_kind": "DEV_FALLBACK",
            "real_openid_kind": "REAL_OR_EXTERNAL",
            "real_openid_tail": real_openid[-4:] if real_openid else None,
            "template_id": settings.wx_template_live_start,
            "grant_available_to_move": available,
            "old_ambiguous_delivery_count": snap["old_ambiguous_count"],
            "user_merge_performed": False,
            "old_ambiguous_delivery_replayed": False,
            "follow_transfer_performed": False,
            "preference_transfer_performed": False,
            "real_wechat_called": False,
            "provider_exactly_once_claimed": False,
            "notification_exactly_once_claimed": False,
            "production_approved": False,
        }

        if not args.apply:
            print(json.dumps({
                **base_payload,
                "status": "READY",
                "database_write_performed": False,
                "planned_action": "MOVE_GRANT_LEDGER_ONLY",
                "next_action": (
                    "rerun with --fallback-user-id "
                    f"{args.fallback_user_id} --real-user-id {args.real_user_id} --apply"
                ),
            }, ensure_ascii=False, indent=2))
            return 0

        async with engine.begin() as connection:
            # Lock both identities and both possible grant rows before the move.
            locked_users = (
                await connection.execute(
                    text(
                        "SELECT id, openid FROM users "
                        "WHERE id IN (:fallback_user_id, :real_user_id) "
                        "ORDER BY id FOR UPDATE"
                    ),
                    {
                        "fallback_user_id": args.fallback_user_id,
                        "real_user_id": args.real_user_id,
                    },
                )
            ).mappings().all()
            locked_by_id = {int(row["id"]): str(row["openid"]) for row in locked_users}
            if locked_by_id.get(args.fallback_user_id) != fallback_openid:
                raise RuntimeError("fallback identity changed after READY snapshot")
            if locked_by_id.get(args.real_user_id) != real_openid:
                raise RuntimeError("real identity changed after READY snapshot")

            locked_fallback = (
                await connection.execute(
                    text(
                        "SELECT id, granted_count, consumed_count "
                        "FROM wechat_subscription_grants "
                        "WHERE user_id=:user_id AND template_id=:template_id FOR UPDATE"
                    ),
                    {
                        "user_id": args.fallback_user_id,
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()
            locked_real = (
                await connection.execute(
                    text(
                        "SELECT id FROM wechat_subscription_grants "
                        "WHERE user_id=:user_id AND template_id=:template_id FOR UPDATE"
                    ),
                    {
                        "user_id": args.real_user_id,
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()
            if locked_fallback is None or locked_real is not None:
                raise RuntimeError("grant ledger changed after READY snapshot")
            if (
                int(locked_fallback["granted_count"]) != granted
                or int(locked_fallback["consumed_count"]) != consumed
            ):
                raise RuntimeError("fallback grant counts changed after READY snapshot")

            moved_id = await connection.scalar(
                text(
                    "UPDATE wechat_subscription_grants SET user_id=:real_user_id "
                    "WHERE id=:grant_id AND user_id=:fallback_user_id RETURNING id"
                ),
                {
                    "real_user_id": args.real_user_id,
                    "grant_id": int(locked_fallback["id"]),
                    "fallback_user_id": args.fallback_user_id,
                },
            )
            if moved_id is None:
                raise RuntimeError("grant move lost its locked source row")

        async with engine.connect() as connection:
            after = await _snapshot(connection, args.fallback_user_id, args.real_user_id)

        after_real_grant = after["real_grant"]
        fallback_grant_remaining = after["fallback_grant"] is not None
        real_available_after = (
            max(
                0,
                int(after_real_grant["granted_count"]) - int(after_real_grant["consumed_count"]),
            )
            if after_real_grant is not None
            else 0
        )
        passed = (
            not fallback_grant_remaining
            and after_real_grant is not None
            and real_available_after == available
            and after["old_ambiguous_count"] == snap["old_ambiguous_count"]
        )
        print(json.dumps({
            **base_payload,
            "status": "CONVERGED" if passed else "FAIL",
            "database_write_performed": True,
            "grant_moved_to_real_user": after_real_grant is not None,
            "fallback_grant_remaining": fallback_grant_remaining,
            "real_grant_available_after": real_available_after,
            "old_ambiguous_delivery_count_after": after["old_ambiguous_count"],
            "old_ambiguous_delivery_preserved": (
                after["old_ambiguous_count"] == snap["old_ambiguous_count"]
            ),
            "grant_consumed": False,
            "safe_to_prepare_new_event": passed,
        }, ensure_ascii=False, indent=2))
        return 0 if passed else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
