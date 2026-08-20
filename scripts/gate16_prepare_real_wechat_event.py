#!/usr/bin/env python3
"""Prepare one post-follow canonical LIVE_STARTED event for Gate 1.6-5.

This is a controlled acceptance fixture for the notification gate. It does not
call any livestream provider or WeChat, does not consume a grant, and does not
insert a LiveEvent directly. Instead it:

1. verifies the real test user and a positive WeChat grant already exist;
2. creates one disabled, isolated acceptance account so production monitoring
   will never probe the synthetic provider identity;
3. creates the user's formal Follow + enabled NotificationPreference;
4. records OFFLINE, LIVE, LIVE monitor observations through the formal
   LiveObservationApplicationService; and
5. consumes the decisive second LIVE through the normal reconstruction/reducer/
   transition persistence chain to create a new canonical
   LIVE_STARTED / TRANSITION event after the Follow timestamp.

Gate 0A remains DEGRADED: this controlled notification acceptance fixture is not
real-provider lifecycle evidence and must never be used to close that gap.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.domain.creators import Creator, PlatformAccount
from stage_letter.domain.live import LiveEventCause, LiveEventType, LiveObservation, LiveStatus
from stage_letter.infrastructure.db.models import FollowModel, UserModel
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from workers.composition import build_worker_services

EXPECTED_HEAD = "a63f4b2d9e71"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        required=True,
        help="formal numeric user id that already owns one positive real WeChat grant",
    )
    return parser


def _observation(
    observation_id: str,
    account_id: str,
    status: LiveStatus,
    observed_at: datetime,
    *,
    source_started_at: datetime | None = None,
) -> LiveObservation:
    return LiveObservation(
        observation_id=observation_id,
        account_id=account_id,
        status=status,
        observed_at=observed_at,
        source="gate16.real-wechat-prep",
        source_started_at=source_started_at,
    )


async def _blocked(reason: str, **extra) -> int:
    payload = {
        "gate": "1.6-5",
        "probe": "prepare_post_follow_event",
        "status": "BLOCKED",
        "reason": reason,
        "real_provider_called": False,
        "real_wechat_called": False,
        "grant_consumed": False,
        "gate0a_lifecycle_claimed": False,
        "production_approved": False,
    }
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2


async def _main(args: argparse.Namespace) -> int:
    if not args.user_id.isdigit():
        return await _blocked("--user-id must be a numeric formal user id")
    if not settings.wx_template_live_start:
        return await _blocked("WX_TEMPLATE_LIVE_START is not configured")

    user_id = int(args.user_id)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if head != EXPECTED_HEAD:
            return await _blocked(
                "migration head mismatch",
                expected_head=EXPECTED_HEAD,
                observed_head=head,
            )

        async with sessions() as session:
            user = await session.get(UserModel, user_id)
        if user is None or not user.openid:
            return await _blocked("formal test user/openid not found", user_id=args.user_id)

        def uow_factory() -> SQLAlchemyUnitOfWork:
            return SQLAlchemyUnitOfWork(sessions)

        async with uow_factory() as uow:
            grant_before = await uow.grants.get_wechat_grant(
                args.user_id,
                settings.wx_template_live_start,
            )
        if grant_before is None or grant_before.available <= 0:
            return await _blocked(
                "real WeChat grant is missing or exhausted",
                user_id=args.user_id,
                grant_available=(grant_before.available if grant_before else 0),
            )

        suffix = secrets.randbelow(900_000_000) + 100_000_000
        creator_pk = 8_160_500_000_000_000 + suffix * 10
        account_pk = creator_pk + 1
        creator_id = str(creator_pk)
        account_id = str(account_pk)
        provider_identity = f"gate16-5-controlled-{secrets.token_hex(8)}"

        bundle = build_worker_services(sessions)

        # Two separate commits intentionally keep persistence ordering explicit.
        await bundle.creators.save_bundle(Creator(creator_id))
        await bundle.creators.save_bundle(
            Creator(creator_id),
            account=PlatformAccount(
                account_id=account_id,
                creator_id=creator_id,
                platform="gate16_acceptance",
                platform_user_id=provider_identity,
                enabled=False,
            ),
        )

        await bundle.follows.follow_account(
            user_id=args.user_id,
            account_id=account_id,
            starred=False,
        )

        async with engine.connect() as connection:
            follow_created_at = await connection.scalar(
                select(FollowModel.created_at).where(
                    FollowModel.user_id == user_id,
                    FollowModel.platform_account_id == account_pk,
                )
            )
        if follow_created_at is None:
            return await _blocked(
                "formal Follow was not persisted",
                user_id=args.user_id,
                account_id=account_id,
            )

        now = datetime.now(timezone.utc).replace(microsecond=0)
        t0 = max(now, follow_created_at + timedelta(seconds=1))
        token = secrets.token_hex(10)
        observations = (
            _observation(
                f"monitor:gate16-real-prep-{token}-offline",
                account_id,
                LiveStatus.OFFLINE,
                t0,
            ),
            _observation(
                f"monitor:gate16-real-prep-{token}-live-1",
                account_id,
                LiveStatus.LIVE,
                t0 + timedelta(seconds=1),
                source_started_at=t0,
            ),
            _observation(
                f"monitor:gate16-real-prep-{token}-live-2",
                account_id,
                LiveStatus.LIVE,
                t0 + timedelta(seconds=2),
                source_started_at=t0,
            ),
        )

        for observation in observations:
            await bundle.live_observations.record(observation)

        result = await bundle.live_observation_consumer.consume(
            account_id,
            observations[2].observation_id,
        )
        transition = result.transition
        if transition is None:
            return await _blocked(
                "controlled OFFLINE -> LIVE confirmation emitted no transition",
                user_id=args.user_id,
                account_id=account_id,
            )

        event = transition.event
        if (
            event.event_type is not LiveEventType.LIVE_STARTED
            or event.cause is not LiveEventCause.TRANSITION
        ):
            return await _blocked(
                "prepared canonical event is not LIVE_STARTED / TRANSITION",
                event_id=event.event_id,
                event_type=event.event_type.value,
                event_cause=event.cause.value,
            )

        async with uow_factory() as uow:
            preference = await uow.follows.get_notification_preference(
                args.user_id,
                account_id,
            )
            grant_after = await uow.grants.get_wechat_grant(
                args.user_id,
                settings.wx_template_live_start,
            )

        event_after_follow = event.occurred_at >= follow_created_at
        grant_unchanged = (
            grant_after is not None
            and grant_after.granted_count == grant_before.granted_count
            and grant_after.consumed_count == grant_before.consumed_count
        )
        passed = bool(
            event_after_follow
            and preference is not None
            and preference.enabled
            and grant_unchanged
        )

        print(
            json.dumps(
                {
                    "gate": "1.6-5",
                    "probe": "prepare_post_follow_event",
                    "status": "PREPARED" if passed else "FAIL",
                    "migration_head": head,
                    "user_id": args.user_id,
                    "account_id": account_id,
                    "account_enabled_for_monitoring": False,
                    "follow_created_at": follow_created_at.isoformat(),
                    "notification_preference_enabled": (
                        preference.enabled if preference is not None else False
                    ),
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "event_cause": event.cause.value,
                    "event_occurred_at": event.occurred_at.isoformat(),
                    "event_after_follow": event_after_follow,
                    "transition_reused_existing": transition.reused_existing,
                    "grant_available_before": grant_before.available,
                    "grant_available_after": grant_after.available if grant_after else 0,
                    "grant_consumed": not grant_unchanged,
                    "real_provider_called": False,
                    "real_wechat_called": False,
                    "controlled_notification_fixture": True,
                    "gate0a_lifecycle_claimed": False,
                    "provider_exactly_once_claimed": False,
                    "notification_exactly_once_claimed": False,
                    "production_approved": False,
                    "next_action": (
                        "run gate16_real_wechat_acceptance.py without --send and verify ARMED"
                    ),
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
