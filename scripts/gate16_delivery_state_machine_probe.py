#!/usr/bin/env python3
"""Gate 1.6-3 real PostgreSQL delivery state-machine acceptance probe."""
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

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stage_letter.application.services.notification_delivery import (
    NotificationDeliveryApplicationService,
)
from stage_letter.domain.notifications import DeliveryChannel, DeliveryKey, DeliveryState
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


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


async def _delivery_snapshot(engine, delivery_id: int) -> dict[str, object]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                select(
                    NotificationDeliveryModel.state,
                    NotificationDeliveryModel.attempt,
                    NotificationDeliveryModel.next_attempt_at,
                    NotificationDeliveryModel.in_flight_at,
                    NotificationDeliveryModel.sent_at,
                    NotificationDeliveryModel.error_code,
                ).where(NotificationDeliveryModel.id == delivery_id)
            )
        ).one()
    return {
        "state": row.state,
        "attempt": row.attempt,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "in_flight_at": row.in_flight_at.isoformat() if row.in_flight_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "error_code": row.error_code,
    }


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        index_names = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE tablename = 'notification_deliveries'
                        """
                    )
                )
            ).scalars()
        )

    if head != EXPECTED_HEAD:
        print(
            json.dumps(
                {
                    "gate": "1.6-3",
                    "status": "BLOCKED",
                    "reason": "migration head mismatch",
                    "expected_head": EXPECTED_HEAD,
                    "observed_head": head,
                    "production_approved": False,
                },
                indent=2,
            )
        )
        await engine.dispose()
        return 2

    required_indexes = {
        "idx_g163_delivery_due",
        "idx_g163_delivery_inflight",
    }
    if not required_indexes.issubset(index_names):
        print(
            json.dumps(
                {
                    "gate": "1.6-3",
                    "status": "BLOCKED",
                    "reason": "delivery execution index missing",
                    "missing_indexes": sorted(required_indexes - index_names),
                    "production_approved": False,
                },
                indent=2,
            )
        )
        await engine.dispose()
        return 2

    suffix = secrets.randbelow(300_000_000) + 100_000_000
    creator_id = 6_200_000_000_000_000_000 + suffix * 10
    account_id = creator_id + 1
    session_id = creator_id + 2
    event_pk = creator_id + 3
    user1_id = creator_id + 4
    user2_id = creator_id + 5
    delivery1_id = creator_id + 6
    delivery2_id = creator_id + 7
    event_id = f"live-event:gate16-3-{secrets.token_hex(12)}"
    t0 = datetime.now(timezone.utc).replace(microsecond=0)

    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO creators (id) VALUES (:id)"),
            {"id": creator_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform_accounts (
                    id, creator_id, platform, platform_user_id, is_disabled
                ) VALUES (
                    :id, :creator_id, 'douyin', :platform_user_id, false
                )
                """
            ),
            {
                "id": account_id,
                "creator_id": creator_id,
                "platform_user_id": f"gate16-3-{secrets.token_hex(8)}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO live_sessions (
                    id, platform_account_id, started_at, origin
                ) VALUES (
                    :id, :account_id, :started_at, 'TRANSITION'
                )
                """
            ),
            {"id": session_id, "account_id": account_id, "started_at": t0},
        )
        await connection.execute(
            text(
                """
                INSERT INTO live_events (
                    id, event_id, platform_account_id, live_session_id,
                    event_type, cause, occurred_at
                ) VALUES (
                    :id, :event_id, :account_id, :session_id,
                    'LIVE_STARTED', 'TRANSITION', :occurred_at
                )
                """
            ),
            {
                "id": event_pk,
                "event_id": event_id,
                "account_id": account_id,
                "session_id": session_id,
                "occurred_at": t0,
            },
        )
        for user_id in (user1_id, user2_id):
            await connection.execute(
                text("INSERT INTO users (id, openid) VALUES (:id, :openid)"),
                {"id": user_id, "openid": f"gate16-3-openid-{user_id}"},
            )
        await connection.execute(
            text(
                """
                INSERT INTO notification_deliveries (
                    id, user_id, live_event_id, live_session_id,
                    channel, state, attempt, created_at, updated_at
                ) VALUES (
                    :id, :user_id, :event_pk, :session_id,
                    'WECHAT_SUBSCRIBE', 'PENDING', 0, :created_at, :created_at
                )
                """
            ),
            {
                "id": delivery1_id,
                "user_id": user1_id,
                "event_pk": event_pk,
                "session_id": session_id,
                "created_at": t0,
            },
        )

    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(sessions)

    service = NotificationDeliveryApplicationService(uow_factory)
    user1_key = DeliveryKey(str(user1_id), event_id, DeliveryChannel.WECHAT_SUBSCRIBE)
    user2_key = DeliveryKey(str(user2_id), event_id, DeliveryChannel.WECHAT_SUBSCRIBE)

    try:
        concurrent = await asyncio.gather(
            service.claim_next_due(now=t0 + timedelta(seconds=1)),
            service.claim_next_due(now=t0 + timedelta(seconds=1)),
        )
        claimed = [item for item in concurrent if item is not None]
        after_claim = await _delivery_snapshot(engine, delivery1_id)

        # Simulate losing the process after durable IN_FLIGHT claim and before a
        # trustworthy provider outcome is persisted.
        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        def restarted_uow_factory() -> SQLAlchemyUnitOfWork:
            return SQLAlchemyUnitOfWork(sessions)

        restarted = NotificationDeliveryApplicationService(restarted_uow_factory)
        recovery = await restarted.recover_stale_in_flight(
            now=t0 + timedelta(seconds=121),
            stale_after_seconds=60,
        )
        after_recovery = await _delivery_snapshot(engine, delivery1_id)
        claim_after_ambiguous = await restarted.claim_next_due(
            now=t0 + timedelta(seconds=122)
        )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO notification_deliveries (
                        id, user_id, live_event_id, live_session_id,
                        channel, state, attempt, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :event_pk, :session_id,
                        'WECHAT_SUBSCRIBE', 'PENDING', 0, :created_at, :created_at
                    )
                    """
                ),
                {
                    "id": delivery2_id,
                    "user_id": user2_id,
                    "event_pk": event_pk,
                    "session_id": session_id,
                    "created_at": t0,
                },
            )

        retry_first_claim = await restarted.claim_next_due(
            now=t0 + timedelta(seconds=130)
        )
        if retry_first_claim is None or retry_first_claim.key != user2_key:
            raise RuntimeError("retry acceptance delivery was not claimed")

        waiting = await restarted.schedule_retry(
            user2_key,
            now=t0 + timedelta(seconds=131),
            delay_seconds=30,
            error_code="TEMPORARY_ACCEPTANCE_ERROR",
        )
        claim_before_due = await restarted.claim_next_due(
            now=t0 + timedelta(seconds=160)
        )
        retry_second_claim = await restarted.claim_next_due(
            now=t0 + timedelta(seconds=161)
        )
        if retry_second_claim is None or retry_second_claim.key != user2_key:
            raise RuntimeError("due retry was not reclaimed")
        sent = await restarted.mark_sent(
            user2_key,
            now=t0 + timedelta(seconds=162),
        )
        claim_after_sent = await restarted.claim_next_due(
            now=t0 + timedelta(seconds=200)
        )
        after_sent = await _delivery_snapshot(engine, delivery2_id)

        async with engine.connect() as connection:
            ambiguous_count = await connection.scalar(
                select(func.count()).select_from(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.id.in_([delivery1_id, delivery2_id]),
                    NotificationDeliveryModel.state == DeliveryState.AMBIGUOUS.value,
                )
            )
            sent_count = await connection.scalar(
                select(func.count()).select_from(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.id.in_([delivery1_id, delivery2_id]),
                    NotificationDeliveryModel.state == DeliveryState.SENT.value,
                )
            )

        checks = {
            "concurrent_claim_one_winner": len(claimed) == 1,
            "first_delivery_in_flight": after_claim["state"] == "IN_FLIGHT"
            and after_claim["attempt"] == 1,
            "restart_recovered_ambiguous": recovery.recovered_ambiguous == 1
            and after_recovery["state"] == "AMBIGUOUS",
            "ambiguous_not_reclaimed": claim_after_ambiguous is None,
            "waiting_retry_state": waiting.state is DeliveryState.WAITING_RETRY
            and waiting.attempt == 1,
            "retry_not_claimed_early": claim_before_due is None,
            "retry_attempt_incremented": retry_second_claim.attempt == 2,
            "sent_terminal": sent.state is DeliveryState.SENT
            and sent.is_terminal
            and after_sent["state"] == "SENT",
            "sent_not_reclaimed": claim_after_sent is None,
            "final_state_counts": int(ambiguous_count or 0) == 1
            and int(sent_count or 0) == 1,
        }
        status = "PASS" if all(checks.values()) else "FAIL"

        print(
            json.dumps(
                {
                    "gate": "1.6-3",
                    "status": status,
                    "migration_head": head,
                    "execution_indexes_present": True,
                    "concurrent_claim_non_null_count": len(claimed),
                    "first_delivery_after_claim": after_claim,
                    "restart_recovery": {
                        "examined": recovery.examined,
                        "recovered_ambiguous": recovery.recovered_ambiguous,
                    },
                    "first_delivery_after_recovery": after_recovery,
                    "claim_after_ambiguous": claim_after_ambiguous is not None,
                    "retry_first_attempt": retry_first_claim.attempt,
                    "waiting_retry_state": waiting.state.value,
                    "retry_before_due_claimed": claim_before_due is not None,
                    "retry_second_attempt": retry_second_claim.attempt,
                    "sent_state": sent.state.value,
                    "sent_terminal": sent.is_terminal,
                    "claim_after_sent": claim_after_sent is not None,
                    "final_ambiguous_count": int(ambiguous_count or 0),
                    "final_sent_count": int(sent_count or 0),
                    "checks": checks,
                    "wechat_provider_called": False,
                    "worker_exactly_once_claimed": False,
                    "provider_exactly_once_claimed": False,
                    "notification_exactly_once_claimed": False,
                    "production_approved": False,
                },
                indent=2,
                default=str,
            )
        )
        return 0 if status == "PASS" else 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.id.in_([delivery1_id, delivery2_id])
                )
            )
            await connection.execute(delete(LiveEventModel).where(LiveEventModel.id == event_pk))
            await connection.execute(delete(LiveSessionModel).where(LiveSessionModel.id == session_id))
            await connection.execute(delete(PlatformAccountModel).where(PlatformAccountModel.id == account_id))
            await connection.execute(delete(CreatorModel).where(CreatorModel.id == creator_id))
            await connection.execute(UserModel.__table__.delete().where(UserModel.id.in_([user1_id, user2_id])))
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
