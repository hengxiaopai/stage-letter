#!/usr/bin/env python3
"""Gate 1.6-5 PostgreSQL atomic-finalize + restart acceptance probe."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from stage_letter.application.services.notification_delivery import (
    NotificationDeliveryApplicationService,
)
from stage_letter.application.services.wechat_finalize import (
    WeChatDeliveryFinalizationApplicationService,
)
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    LiveEventModel,
    LiveSessionModel,
    NotificationDeliveryModel,
    PlatformAccountModel,
    UserModel,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


EXPECTED_HEAD = "a63f4b2d9e71"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"
TEMPLATE_ID = "gate16-5-template"


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


async def _grant_consumed(engine, user_id: int) -> int:
    async with engine.connect() as connection:
        value = await connection.scalar(
            text(
                "SELECT consumed_count FROM wechat_subscription_grants "
                "WHERE user_id=:user_id AND template_id=:template_id"
            ),
            {"user_id": user_id, "template_id": TEMPLATE_ID},
        )
    return int(value)


async def _delivery_state(engine, delivery_id: int) -> str:
    async with engine.connect() as connection:
        value = await connection.scalar(
            select(NotificationDeliveryModel.state).where(
                NotificationDeliveryModel.id == delivery_id
            )
        )
    return str(value)


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if head != EXPECTED_HEAD:
        print(json.dumps({
            "gate": "1.6-5",
            "status": "BLOCKED",
            "reason": "migration head mismatch",
            "expected_head": EXPECTED_HEAD,
            "observed_head": head,
            "production_approved": False,
        }, indent=2))
        await engine.dispose()
        return 2

    seed = 9_160_500_000 + secrets.randbelow(100_000)
    user_id = seed + 1
    creator_id = seed + 2
    account_id = seed + 3
    session_one_id = seed + 4
    session_two_id = seed + 5
    event_one_id = seed + 6
    event_two_id = seed + 7
    delivery_one_id = seed + 8
    delivery_two_id = seed + 9
    grant_id = seed + 10
    event_one_key = f"live-event:gate16-5:{seed}:accepted"
    event_two_key = f"live-event:gate16-5:{seed}:crash"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_claim_at = now - timedelta(minutes=5)

    async def cleanup(target_engine) -> None:
        async with target_engine.begin() as connection:
            await connection.execute(
                delete(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.id.in_([delivery_one_id, delivery_two_id])
                )
            )
            await connection.execute(
                delete(LiveEventModel).where(
                    LiveEventModel.id.in_([event_one_id, event_two_id])
                )
            )
            await connection.execute(
                delete(LiveSessionModel).where(
                    LiveSessionModel.id.in_([session_one_id, session_two_id])
                )
            )
            await connection.execute(
                text(
                    "DELETE FROM wechat_subscription_grants "
                    "WHERE user_id=:user_id AND template_id=:template_id"
                ),
                {"user_id": user_id, "template_id": TEMPLATE_ID},
            )
            await connection.execute(
                delete(PlatformAccountModel).where(PlatformAccountModel.id == account_id)
            )
            await connection.execute(delete(CreatorModel).where(CreatorModel.id == creator_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))

    try:
        async with sessions() as session:
            # These probe fixtures intentionally use explicit flush barriers.
            # The formal models do not declare ORM relationships, so relying on
            # one large flush can let child rows reach PostgreSQL before their
            # referenced parents even though the database FKs are correct.
            session.add(UserModel(id=user_id, openid=f"gate16-5-{seed}"))
            session.add(CreatorModel(id=creator_id))
            await session.flush()

            session.add(
                PlatformAccountModel(
                    id=account_id,
                    creator_id=creator_id,
                    platform="douyin",
                    platform_user_id=f"gate16-5-{seed}",
                    canonical_url=None,
                    is_disabled=False,
                )
            )
            await session.flush()

            session.add_all([
                LiveSessionModel(
                    id=session_one_id,
                    platform_account_id=account_id,
                    opened_at=now - timedelta(minutes=10),
                    closed_at=now - timedelta(minutes=9),
                    origin="TRANSITION",
                ),
                LiveSessionModel(
                    id=session_two_id,
                    platform_account_id=account_id,
                    opened_at=now - timedelta(minutes=8),
                    origin="TRANSITION",
                ),
            ])
            await session.flush()

            session.add_all([
                LiveEventModel(
                    id=event_one_id,
                    event_id=event_one_key,
                    platform_account_id=account_id,
                    live_session_id=session_one_id,
                    event_type="LIVE_STARTED",
                    cause="TRANSITION",
                    occurred_at=now - timedelta(minutes=10),
                ),
                LiveEventModel(
                    id=event_two_id,
                    event_id=event_two_key,
                    platform_account_id=account_id,
                    live_session_id=session_two_id,
                    event_type="LIVE_STARTED",
                    cause="TRANSITION",
                    occurred_at=now - timedelta(minutes=8),
                ),
            ])
            await session.flush()

            session.add_all([
                NotificationDeliveryModel(
                    id=delivery_one_id,
                    user_id=user_id,
                    live_event_id=event_one_id,
                    live_session_id=session_one_id,
                    channel="WECHAT_SUBSCRIBE",
                    state="PENDING",
                    attempt=0,
                    created_at=now - timedelta(minutes=10),
                    updated_at=now - timedelta(minutes=10),
                ),
                NotificationDeliveryModel(
                    id=delivery_two_id,
                    user_id=user_id,
                    live_event_id=event_two_id,
                    live_session_id=session_two_id,
                    channel="WECHAT_SUBSCRIBE",
                    state="PENDING",
                    attempt=0,
                    created_at=now - timedelta(minutes=8),
                    updated_at=now - timedelta(minutes=8),
                ),
            ])
            await session.flush()

            await session.execute(
                text(
                    "INSERT INTO wechat_subscription_grants "
                    "(id,user_id,template_id,granted_count,consumed_count,updated_at) "
                    "VALUES (:id,:user_id,:template_id,2,0,:now)"
                ),
                {
                    "id": grant_id,
                    "user_id": user_id,
                    "template_id": TEMPLATE_ID,
                    "now": now,
                },
            )
            await session.commit()

        def uow_factory():
            return SQLAlchemyUnitOfWork(sessions)

        delivery_service = NotificationDeliveryApplicationService(uow_factory)
        finalizer = WeChatDeliveryFinalizationApplicationService(uow_factory)

        first_claim = await delivery_service.claim_next_due(now=now)
        assert first_claim is not None and first_claim.key.live_event_id == event_one_key
        accepted = ProviderOutcome(
            ProviderOutcomeKind.ACCEPTED,
            GrantEffect.CONSUME,
            provider_code="0",
            provider_message="ok",
        )
        finalized = await finalizer.finalize(
            first_claim,
            template_id=TEMPLATE_ID,
            outcome=accepted,
            now=now + timedelta(seconds=1),
        )
        consumed_after_success = await _grant_consumed(engine, user_id)

        duplicate_rejected = False
        try:
            await finalizer.finalize(
                first_claim,
                template_id=TEMPLATE_ID,
                outcome=accepted,
                now=now + timedelta(seconds=2),
            )
        except ApplicationInvariantError:
            duplicate_rejected = True
        consumed_after_duplicate = await _grant_consumed(engine, user_id)

        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        restart_sent_state = await _delivery_state(engine, delivery_one_id)
        restart_consumed = await _grant_consumed(engine, user_id)

        def restarted_uow_factory():
            return SQLAlchemyUnitOfWork(sessions)

        restarted_delivery_service = NotificationDeliveryApplicationService(restarted_uow_factory)
        second_claim = await restarted_delivery_service.claim_next_due(now=stale_claim_at)
        assert second_claim is not None and second_claim.key.live_event_id == event_two_key

        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        def recovered_uow_factory():
            return SQLAlchemyUnitOfWork(sessions)

        recovery_service = NotificationDeliveryApplicationService(recovered_uow_factory)
        recovery = await recovery_service.recover_stale_in_flight(
            now=now,
            stale_after_seconds=60,
        )
        crash_state = await _delivery_state(engine, delivery_two_id)
        consumed_after_crash_recovery = await _grant_consumed(engine, user_id)
        claim_after_recovery = await recovery_service.claim_next_due(now=now + timedelta(hours=1))

        checks = {
            "accepted_became_sent": finalized.delivery.state.value == "SENT",
            "accepted_consumed_once": consumed_after_success == 1,
            "duplicate_finalize_rejected": duplicate_rejected,
            "duplicate_did_not_consume_again": consumed_after_duplicate == 1,
            "restart_preserved_sent": restart_sent_state == "SENT",
            "restart_preserved_consumption": restart_consumed == 1,
            "crash_recovered_ambiguous": crash_state == "AMBIGUOUS" and recovery.recovered_ambiguous == 1,
            "crash_did_not_consume_grant": consumed_after_crash_recovery == 1,
            "ambiguous_not_reclaimed": claim_after_recovery is None,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        print(json.dumps({
            "gate": "1.6-5",
            "probe": "postgresql_atomic_finalize_restart",
            "status": status,
            "migration_head": head,
            "accepted_delivery_state": finalized.delivery.state.value,
            "grant_consumed_after_success": consumed_after_success,
            "duplicate_finalize_rejected": duplicate_rejected,
            "grant_consumed_after_duplicate": consumed_after_duplicate,
            "restart_sent_state": restart_sent_state,
            "restart_grant_consumed": restart_consumed,
            "restart_recovery": {
                "examined": recovery.examined,
                "recovered_ambiguous": recovery.recovered_ambiguous,
                "delivery_state": crash_state,
            },
            "grant_consumed_after_crash_recovery": consumed_after_crash_recovery,
            "claim_after_ambiguous": claim_after_recovery is not None,
            "checks": checks,
            "real_wechat_called": False,
            "worker_exactly_once_claimed": False,
            "provider_exactly_once_claimed": False,
            "notification_exactly_once_claimed": False,
            "production_approved": False,
        }, indent=2))
        return 0 if status == "PASS" else 1
    finally:
        try:
            await cleanup(engine)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
