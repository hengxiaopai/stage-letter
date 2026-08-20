#!/usr/bin/env python3
"""Gate 1.6-5 guarded real-WeChat acceptance.

Without ``--send`` this probe is read-only and returns an ARMED plan. With
``--send`` it sends exactly one real subscribe message. It never creates or
edits live observations/sessions/events; it reuses an already-persisted canonical
LIVE_STARTED/TRANSITION event. The send path creates only the test user's logical
PENDING delivery when absent, claims it, sends once, atomically finalizes the
provider outcome + grant effect, restarts the DB runtime, and verifies the result.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.application.notification_providers import WeChatLiveStartMessage
from stage_letter.application.services.wechat_finalize import (
    WeChatAtomicDeliveryAttemptApplicationService,
    WeChatDeliveryFinalizationApplicationService,
)
from stage_letter.domain.notification_policy import (
    NotificationTarget,
    build_pending_delivery,
    evaluate_notification_eligibility,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    claim_delivery,
    resolve_wechat_grant_state,
)
from stage_letter.infrastructure.db.models import UserModel
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.notifications.wechat import (
    HttpxWeChatProviderGateway,
    WeChatSubscribeFormalAdapter,
)

EXPECTED_HEAD = "a63f4b2d9e71"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="formal numeric test user id; auto-selects only when unambiguous")
    parser.add_argument("--event-id", help="existing canonical LIVE_STARTED/TRANSITION event id")
    parser.add_argument("--room-title", default="开场信 Gate 1.6 真实通知验收")
    parser.add_argument("--send", action="store_true", help="actually send one real WeChat message")
    return parser


async def _auto_user_id(engine, template_id: str) -> tuple[str | None, list[str]]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT CAST(u.id AS TEXT) AS user_id
                    FROM users AS u
                    JOIN wechat_subscription_grants AS g ON g.user_id = u.id
                    WHERE g.template_id = :template_id
                      AND g.granted_count - g.consumed_count > 0
                      AND u.openid IS NOT NULL
                      AND u.openid <> ''
                    ORDER BY u.id
                    LIMIT 10
                    """
                ),
                {"template_id": template_id},
            )
        ).mappings().all()
    candidates = [row["user_id"] for row in rows]
    return (candidates[0] if len(candidates) == 1 else None, candidates)


async def _auto_event_id(engine, user_id: str) -> str | None:
    async with engine.connect() as connection:
        value = await connection.scalar(
            text(
                """
                SELECT le.event_id
                FROM live_events AS le
                JOIN follows AS f
                  ON f.platform_account_id = le.platform_account_id
                 AND f.user_id = :user_id
                 AND f.created_at <= le.occurred_at
                JOIN notification_preferences AS np
                  ON np.platform_account_id = le.platform_account_id
                 AND np.user_id = :user_id
                 AND np.enabled = TRUE
                WHERE le.event_id IS NOT NULL
                  AND le.live_session_id IS NOT NULL
                  AND le.event_type = 'LIVE_STARTED'
                  AND le.cause = 'TRANSITION'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM notification_deliveries AS nd
                      WHERE nd.user_id = :user_id
                        AND nd.live_event_id = le.id
                        AND nd.channel = 'WECHAT_SUBSCRIBE'
                  )
                ORDER BY le.occurred_at DESC, le.id DESC
                LIMIT 1
                """
            ),
            {"user_id": int(user_id)},
        )
    return None if value is None else str(value)


async def _block(reason: str, **extra) -> int:
    payload = {
        "gate": "1.6-5",
        "probe": "real_wechat_acceptance",
        "status": "BLOCKED",
        "reason": reason,
        "real_wechat_called": False,
        "provider_exactly_once_claimed": False,
        "notification_exactly_once_claimed": False,
        "production_approved": False,
    }
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2


async def _main(args: argparse.Namespace) -> int:
    if not settings.wx_appid or not settings.wx_secret or not settings.wx_template_live_start:
        return await _block("WX_APPID / WX_SECRET / WX_TEMPLATE_LIVE_START not configured")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if head != EXPECTED_HEAD:
            return await _block(
                "migration head mismatch",
                expected_head=EXPECTED_HEAD,
                observed_head=head,
            )

        user_id = args.user_id
        candidates: list[str] = []
        if user_id is None:
            user_id, candidates = await _auto_user_id(engine, settings.wx_template_live_start)
            if user_id is None:
                return await _block(
                    "test user is ambiguous or no positive-grant user exists",
                    candidate_user_ids=candidates,
                    hint="rerun with --user-id <id> after ensuring a real grant exists",
                )
        if not str(user_id).isdigit():
            return await _block("--user-id must be a numeric formal user id")

        async with sessions() as session:
            user = await session.get(UserModel, int(user_id))
            if user is None or not user.openid:
                return await _block("test user/openid not found", user_id=str(user_id))
            openid = user.openid

        event_id = args.event_id or await _auto_event_id(engine, str(user_id))
        if event_id is None:
            return await _block(
                "no unused canonical LIVE_STARTED/TRANSITION event is eligible for this test user",
                user_id=str(user_id),
                hint="wait for/choose an existing canonical event and rerun with --event-id",
            )

        def uow_factory():
            return SQLAlchemyUnitOfWork(sessions)

        async with uow_factory() as uow:
            event = await uow.live.get_event(event_id)
            if event is None:
                return await _block("canonical event not found", event_id=event_id)
            follow = await uow.follows.get_follow(str(user_id), event.account_id)
            preference = await uow.follows.get_notification_preference(
                str(user_id), event.account_id
            )
            grant_before = await uow.grants.get_wechat_grant(
                str(user_id), settings.wx_template_live_start
            )
            target = NotificationTarget(
                user_id=str(user_id),
                account_id=event.account_id,
                following=follow is not None,
                notification_enabled=(preference.enabled if preference is not None else False),
                grant_state=resolve_wechat_grant_state(grant_before),
            )
            decision = evaluate_notification_eligibility(event, target)
            if not decision.eligible or grant_before is None or grant_before.available <= 0:
                return await _block(
                    "test target is not currently eligible",
                    user_id=str(user_id),
                    event_id=event_id,
                    eligibility_reason=decision.reason.value,
                    grant_available=(grant_before.available if grant_before else 0),
                )
            delivery = build_pending_delivery(decision, event, target)
            assert delivery is not None
            existing = await uow.notifications.get_delivery(delivery.key)
            if existing is not None and existing.state not in {
                DeliveryState.PENDING,
                DeliveryState.WAITING_RETRY,
            }:
                return await _block(
                    "logical delivery already exists in a non-sendable state",
                    delivery_state=existing.state.value,
                    user_id=str(user_id),
                    event_id=event_id,
                )

        async with uow_factory() as uow:
            account = await uow.creators.get_account(delivery.account_id)
            profile = None if account is None else await uow.creators.get_profile(account.creator_id)
        anchor_name = (
            profile.display_name
            if profile is not None and profile.display_name
            else "开场信主播"
        )
        start_time = event.occurred_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M"
        )
        message = WeChatLiveStartMessage(
            openid=openid,
            template_id=settings.wx_template_live_start,
            anchor_name=anchor_name,
            room_title=args.room_title,
            start_time=start_time,
            theme="开播提醒验收",
            activity="Gate 1.6",
        )

        if not args.send:
            print(json.dumps({
                "gate": "1.6-5",
                "probe": "real_wechat_acceptance",
                "status": "ARMED",
                "migration_head": head,
                "user_id": str(user_id),
                "event_id": event_id,
                "delivery_state": (existing.state.value if existing is not None else "NOT_CREATED"),
                "grant_available_before": grant_before.available,
                "real_wechat_called": False,
                "database_write_performed": False,
                "next_action": (
                    f"rerun with --user-id {user_id} --event-id {event_id} --send "
                    "to consume one real grant"
                ),
                "provider_exactly_once_claimed": False,
                "notification_exactly_once_claimed": False,
                "production_approved": False,
            }, ensure_ascii=False, indent=2))
            return 3

        if existing is None:
            async with uow_factory() as uow:
                created = await uow.notifications.create_delivery(delivery)
                if not created:
                    return await _block("logical delivery creation lost a concurrent race")
                await uow.commit()

        key = DeliveryKey(str(user_id), event_id, DeliveryChannel.WECHAT_SUBSCRIBE)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        async with uow_factory() as uow:
            current = await uow.notifications.lock_delivery(key)
            if current is None:
                return await _block("logical delivery is currently locked or missing")
            if not current.is_due(now):
                return await _block(
                    "logical delivery is not due for claim",
                    delivery_state=current.state.value,
                )
            claimed = claim_delivery(current, now=now)
            await uow.notifications.save_delivery(claimed)
            await uow.commit()

        finalizer = WeChatDeliveryFinalizationApplicationService(uow_factory)
        async with httpx.AsyncClient(timeout=10.0) as client:
            gateway = HttpxWeChatProviderGateway(
                appid=settings.wx_appid,
                app_secret=settings.wx_secret,
                client=client,
            )
            provider = WeChatSubscribeFormalAdapter(gateway)
            runtime = WeChatAtomicDeliveryAttemptApplicationService(provider, finalizer)
            result = await runtime.execute(
                claimed,
                message,
                now=datetime.now(timezone.utc).replace(microsecond=0),
            )

        await engine.dispose()
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        def restarted_uow_factory():
            return SQLAlchemyUnitOfWork(sessions)

        async with restarted_uow_factory() as uow:
            restarted_delivery = await uow.notifications.get_delivery(key)
            grant_after = await uow.grants.get_wechat_grant(
                str(user_id), settings.wx_template_live_start
            )
        assert restarted_delivery is not None and grant_after is not None

        accepted = result.provider_outcome.provider_accepted
        grant_delta = grant_after.consumed_count - grant_before.consumed_count
        restart_ok = (
            restarted_delivery.state is DeliveryState.SENT
            if accepted
            else restarted_delivery.state is result.delivery.state
        )
        passed = accepted and result.delivery.state is DeliveryState.SENT and grant_delta == 1 and restart_ok
        status = "PASS" if passed else "BLOCKED"
        print(json.dumps({
            "gate": "1.6-5",
            "probe": "real_wechat_acceptance",
            "status": status,
            "migration_head": head,
            "user_id": str(user_id),
            "event_id": event_id,
            "provider_outcome": {
                "kind": result.provider_outcome.kind.value,
                "provider_code": result.provider_outcome.provider_code,
                "grant_effect": result.provider_outcome.grant_effect.value,
                "provider_accepted": accepted,
            },
            "delivery_state_after_send": result.delivery.state.value,
            "restart_delivery_state": restarted_delivery.state.value,
            "grant_consumed_before": grant_before.consumed_count,
            "grant_consumed_after": grant_after.consumed_count,
            "grant_consumed_delta": grant_delta,
            "real_wechat_called": True,
            "access_token_exposed": False,
            "app_secret_exposed": False,
            "worker_exactly_once_claimed": False,
            "provider_exactly_once_claimed": False,
            "notification_exactly_once_claimed": False,
            "production_approved": passed,
        }, ensure_ascii=False, indent=2))
        return 0 if passed else 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
