#!/usr/bin/env python3
"""Gate 1.6-5 strict real-WeChat identity repair.

This controlled acceptance helper repairs one DEBUG fallback user identity by
exchanging a fresh ``wx.login`` code through the real WeChat ``code2session``
endpoint and rebinding the existing formal user row to the returned real openid.

Safety properties:
- never falls back to ``dev_<hash>``;
- never prints the wx.login code, full openid, app secret, or access token;
- preserves the existing user id, grant ledger, follows, preferences, and
  deliveries by updating only ``users.openid`` (and unionid when returned);
- blocks rather than merging when the real openid already belongs to another
  formal user;
- never sends a subscription message and never consumes a grant.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services.wechat import WeChatError, get_wechat_client
from core.config import settings
from stage_letter.infrastructure.db.models import (
    FollowModel,
    NotificationDeliveryModel,
    NotificationPreferenceModel,
    UserModel,
)

EXPECTED_HEAD = "a63f4b2d9e71"


def _kind(openid: str) -> str:
    return "DEV_FALLBACK" if openid.startswith("dev_") else "REAL"


def _tail(openid: str) -> str:
    return openid[-4:] if openid else ""


def _emit(status: str, reason: str | None = None, **extra) -> int:
    payload = {
        "gate": "1.6-5",
        "probe": "rebind_real_wechat_identity",
        "status": status,
        "real_wechat_login_called": bool(extra.pop("real_wechat_login_called", False)),
        "real_wechat_send_called": False,
        "grant_consumed": False,
        "provider_exactly_once_claimed": False,
        "notification_exactly_once_claimed": False,
        "production_approved": False,
    }
    if reason is not None:
        payload["reason"] = reason
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status in {"REBOUND", "ALREADY_REAL"} else 2


async def _main(args: argparse.Namespace) -> int:
    if not settings.wx_appid or not settings.wx_secret:
        return _emit("BLOCKED", "WX_APPID / WX_SECRET not configured")

    user_id = str(args.user_id)
    if not user_id.isdigit():
        return _emit("BLOCKED", "--user-id must be a numeric formal user id")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if head != EXPECTED_HEAD:
            return _emit(
                "BLOCKED",
                "migration head mismatch",
                expected_head=EXPECTED_HEAD,
                observed_head=head,
            )

        async with sessions() as session:
            user = await session.get(UserModel, int(user_id))
            if user is None:
                return _emit("BLOCKED", "formal user not found", user_id=user_id)
            old_openid = user.openid

            grant_row = (
                await session.execute(
                    text(
                        """
                        SELECT granted_count, consumed_count
                        FROM wechat_subscription_grants
                        WHERE user_id = :user_id AND template_id = :template_id
                        """
                    ),
                    {
                        "user_id": int(user_id),
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()
            grant_before = (
                0
                if grant_row is None
                else max(0, int(grant_row["granted_count"]) - int(grant_row["consumed_count"]))
            )
            follow_count_before = int(
                (await session.scalar(select(func.count()).select_from(FollowModel).where(FollowModel.user_id == int(user_id))))
                or 0
            )
            pref_count_before = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(NotificationPreferenceModel)
                        .where(NotificationPreferenceModel.user_id == int(user_id))
                    )
                )
                or 0
            )
            ambiguous_before = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(NotificationDeliveryModel)
                        .where(
                            NotificationDeliveryModel.user_id == int(user_id),
                            NotificationDeliveryModel.state == "AMBIGUOUS",
                        )
                    )
                )
                or 0
            )

        if _kind(old_openid) != "DEV_FALLBACK":
            return _emit(
                "ALREADY_REAL",
                user_id=user_id,
                migration_head=head,
                openid_kind=_kind(old_openid),
                openid_tail=_tail(old_openid),
                grant_available=grant_before,
                database_write_performed=False,
            )
        if grant_before <= 0:
            return _emit(
                "BLOCKED",
                "no positive real acceptance grant is available for this user",
                user_id=user_id,
                old_openid_kind="DEV_FALLBACK",
                old_openid_tail=_tail(old_openid),
                grant_available=grant_before,
                database_write_performed=False,
            )

        code = getpass.getpass("Paste a fresh wx.login code (hidden): ").strip()
        if not code:
            return _emit(
                "BLOCKED",
                "wx.login code is required",
                user_id=user_id,
                database_write_performed=False,
            )

        try:
            info = await asyncio.to_thread(get_wechat_client().code2session, code)
        except WeChatError as exc:
            return _emit(
                "BLOCKED",
                "strict code2session failed; DEBUG fallback was not used",
                user_id=user_id,
                wechat_error_code=str(exc.errcode),
                real_wechat_login_called=True,
                database_write_performed=False,
            )
        finally:
            code = ""

        real_openid = str(info.get("openid", "")).strip()
        real_unionid = info.get("unionid")
        if not real_openid or _kind(real_openid) != "REAL":
            return _emit(
                "BLOCKED",
                "code2session did not return a usable real openid",
                user_id=user_id,
                real_wechat_login_called=True,
                database_write_performed=False,
            )

        now = datetime.now(timezone.utc)
        async with sessions() as session:
            async with session.begin():
                locked = (
                    await session.execute(
                        select(UserModel).where(UserModel.id == int(user_id)).with_for_update()
                    )
                ).scalar_one_or_none()
                if locked is None:
                    return _emit(
                        "BLOCKED",
                        "formal user disappeared before rebind",
                        user_id=user_id,
                        real_wechat_login_called=True,
                        database_write_performed=False,
                    )
                if locked.openid != old_openid or _kind(locked.openid) != "DEV_FALLBACK":
                    return _emit(
                        "BLOCKED",
                        "user identity changed concurrently; re-diagnose before retrying",
                        user_id=user_id,
                        current_openid_kind=_kind(locked.openid),
                        current_openid_tail=_tail(locked.openid),
                        real_wechat_login_called=True,
                        database_write_performed=False,
                    )

                owner = (
                    await session.execute(
                        select(UserModel.id).where(UserModel.openid == real_openid)
                    )
                ).scalar_one_or_none()
                if owner is not None and int(owner) != int(user_id):
                    return _emit(
                        "BLOCKED",
                        "real openid already belongs to another formal user; automatic merge is forbidden",
                        user_id=user_id,
                        existing_real_user_id=str(owner),
                        new_openid_tail=_tail(real_openid),
                        real_wechat_login_called=True,
                        database_write_performed=False,
                    )

                locked.openid = real_openid
                if isinstance(real_unionid, str) and real_unionid.strip():
                    locked.unionid = real_unionid.strip()
                locked.updated_at = now

        async with sessions() as session:
            rebound = await session.get(UserModel, int(user_id))
            assert rebound is not None
            grant_row_after = (
                await session.execute(
                    text(
                        """
                        SELECT granted_count, consumed_count
                        FROM wechat_subscription_grants
                        WHERE user_id = :user_id AND template_id = :template_id
                        """
                    ),
                    {
                        "user_id": int(user_id),
                        "template_id": settings.wx_template_live_start,
                    },
                )
            ).mappings().one_or_none()
            grant_after = (
                0
                if grant_row_after is None
                else max(
                    0,
                    int(grant_row_after["granted_count"])
                    - int(grant_row_after["consumed_count"]),
                )
            )
            follow_count_after = int(
                (await session.scalar(select(func.count()).select_from(FollowModel).where(FollowModel.user_id == int(user_id))))
                or 0
            )
            pref_count_after = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(NotificationPreferenceModel)
                        .where(NotificationPreferenceModel.user_id == int(user_id))
                    )
                )
                or 0
            )
            ambiguous_after = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(NotificationDeliveryModel)
                        .where(
                            NotificationDeliveryModel.user_id == int(user_id),
                            NotificationDeliveryModel.state == "AMBIGUOUS",
                        )
                    )
                )
                or 0
            )

        preserved = all(
            (
                grant_after == grant_before,
                follow_count_after == follow_count_before,
                pref_count_after == pref_count_before,
                ambiguous_after == ambiguous_before,
                _kind(rebound.openid) == "REAL",
            )
        )
        if not preserved:
            return _emit(
                "BLOCKED",
                "post-rebind invariant verification failed",
                user_id=user_id,
                real_wechat_login_called=True,
                database_write_performed=True,
                manual_review_required=True,
            )

        return _emit(
            "REBOUND",
            user_id=user_id,
            migration_head=head,
            old_openid_kind="DEV_FALLBACK",
            old_openid_tail=_tail(old_openid),
            new_openid_kind="REAL",
            new_openid_tail=_tail(rebound.openid),
            unionid_received=isinstance(real_unionid, str) and bool(real_unionid.strip()),
            grant_available_before=grant_before,
            grant_available_after=grant_after,
            grant_preserved=grant_after == grant_before,
            follow_count_preserved=follow_count_after == follow_count_before,
            preference_count_preserved=pref_count_after == pref_count_before,
            ambiguous_delivery_count_preserved=ambiguous_after == ambiguous_before,
            old_ambiguous_delivery_replayed=False,
            safe_to_prepare_new_event=True,
            real_wechat_login_called=True,
            database_write_performed=True,
        )
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
