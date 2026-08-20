#!/usr/bin/env python3
"""Gate 1.6-2 real PostgreSQL durable notification enqueue acceptance probe."""
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

from stage_letter.application.services.notification_enqueue import (
    NotificationEnqueueApplicationService,
)
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    FollowModel,
    LiveEventModel,
    LiveSessionModel,
    NotificationDeliveryModel,
    NotificationPreferenceModel,
    PlatformAccountModel,
    UserModel,
    WeChatSubscriptionGrantModel,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


EXPECTED_HEAD = "f16e2a7c4d10"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"
TEMPLATE_ID = "gate16-live-start-template"


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    suffix = secrets.randbelow(100_000_000) + 100_000_000
    creator_id = 7_000_000_000_000_000_000 + suffix * 10
    account_pk = creator_id + 1
    session_pk = creator_id + 2
    event_pk = creator_id + 3
    user_ids = [creator_id + 10 + i for i in range(5)]
    event_id = f"live-event:gate16-2:{secrets.token_hex(10)}"
    platform_user_id = f"gate16-enqueue-{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).replace(microsecond=0)

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        index_exists = await connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'follows'
                      AND indexname = 'idx_g16_follows_account_user'
                )
                """
            )
        )
    if head != EXPECTED_HEAD:
        print(json.dumps({
            "gate": "1.6-2",
            "status": "BLOCKED",
            "reason": "migration head mismatch",
            "expected_head": EXPECTED_HEAD,
            "observed_head": head,
            "production_approved": False,
        }, indent=2))
        await engine.dispose()
        return 2

    async with engine.begin() as connection:
        for i, user_id in enumerate(user_ids):
            await connection.execute(
                text("INSERT INTO users (id, openid) VALUES (:id, :openid)"),
                {"id": user_id, "openid": f"gate16-{suffix}-{i}"},
            )
        await connection.execute(
            text("INSERT INTO creators (id) VALUES (:id)"),
            {"id": creator_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO platform_accounts (
                    id, creator_id, platform, platform_user_id, is_disabled
                ) VALUES (:id, :creator_id, 'douyin', :platform_user_id, false)
                """
            ),
            {"id": account_pk, "creator_id": creator_id, "platform_user_id": platform_user_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO live_sessions (
                    id, platform_account_id, started_at, origin
                ) VALUES (:id, :account_id, :started_at, 'TRANSITION')
                """
            ),
            {"id": session_pk, "account_id": account_pk, "started_at": now},
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
                "account_id": account_pk,
                "session_id": session_pk,
                "occurred_at": now,
            },
        )

        # user 0: eligible
        # user 1: early follow, missing preference -> conservative skip
        # user 2: followed after event -> excluded by event-time cutoff
        # user 3: disabled preference
        # user 4: exhausted grant
        follow_times = [
            now - timedelta(minutes=5),
            now - timedelta(minutes=4),
            now + timedelta(minutes=1),
            now - timedelta(minutes=3),
            now - timedelta(minutes=2),
        ]
        for user_id, created_at in zip(user_ids, follow_times):
            await connection.execute(
                text(
                    """
                    INSERT INTO follows (
                        user_id, creator_id, platform_account_id, starred,
                        created_at, updated_at
                    ) VALUES (
                        :user_id, :creator_id, :account_id, false,
                        :created_at, :created_at
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "creator_id": creator_id,
                    "account_id": account_pk,
                    "created_at": created_at,
                },
            )

        for index, enabled in ((0, True), (2, True), (3, False), (4, True)):
            await connection.execute(
                text(
                    """
                    INSERT INTO notification_preferences (
                        user_id, platform_account_id, enabled
                    ) VALUES (:user_id, :account_id, :enabled)
                    """
                ),
                {"user_id": user_ids[index], "account_id": account_pk, "enabled": enabled},
            )

        for index, granted, consumed in (
            (0, 2, 0),
            (1, 2, 0),
            (2, 2, 0),
            (3, 2, 0),
            (4, 1, 1),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO wechat_subscription_grants (
                        user_id, template_id, granted_count, consumed_count
                    ) VALUES (:user_id, :template_id, :granted, :consumed)
                    """
                ),
                {
                    "user_id": user_ids[index],
                    "template_id": TEMPLATE_ID,
                    "granted": granted,
                    "consumed": consumed,
                },
            )

    try:
        service = NotificationEnqueueApplicationService(
            lambda: SQLAlchemyUnitOfWork(sessions)
        )
        first = await service.enqueue_live_event(event_id=event_id, template_id=TEMPLATE_ID)
        second = await service.enqueue_live_event(event_id=event_id, template_id=TEMPLATE_ID)

        async with engine.connect() as connection:
            delivery_count = int(
                await connection.scalar(
                    select(func.count())
                    .select_from(NotificationDeliveryModel)
                    .where(NotificationDeliveryModel.live_event_id == event_pk)
                )
                or 0
            )
            eligible_user_count = int(
                await connection.scalar(
                    select(func.count())
                    .select_from(NotificationDeliveryModel)
                    .where(
                        NotificationDeliveryModel.live_event_id == event_pk,
                        NotificationDeliveryModel.user_id == user_ids[0],
                    )
                )
                or 0
            )

        passed = all((
            bool(index_exists),
            first.examined == 4,
            first.created == 1,
            first.reused_existing == 0,
            first.skipped_missing_preference == 1,
            first.skipped_ineligible == 2,
            second.examined == 4,
            second.created == 0,
            second.reused_existing == 1,
            second.skipped_missing_preference == 1,
            second.skipped_ineligible == 2,
            delivery_count == 1,
            eligible_user_count == 1,
        ))

        print(json.dumps({
            "gate": "1.6-2",
            "status": "PASS" if passed else "FAIL",
            "migration_head": head,
            "fanout_index_present": bool(index_exists),
            "first_enqueue": {
                "examined": first.examined,
                "created": first.created,
                "reused_existing": first.reused_existing,
                "skipped_missing_preference": first.skipped_missing_preference,
                "skipped_ineligible": first.skipped_ineligible,
            },
            "second_enqueue": {
                "examined": second.examined,
                "created": second.created,
                "reused_existing": second.reused_existing,
                "skipped_missing_preference": second.skipped_missing_preference,
                "skipped_ineligible": second.skipped_ineligible,
            },
            "final_delivery_count": delivery_count,
            "eligible_user_delivery_count": eligible_user_count,
            "wechat_provider_called": False,
            "provider_exactly_once_claimed": False,
            "notification_exactly_once_claimed": False,
            "production_approved": False,
        }, indent=2))
        return 0 if passed else 1
    finally:
        async with sessions() as session:
            await session.execute(
                delete(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.live_event_id == event_pk
                )
            )
            await session.execute(
                delete(WeChatSubscriptionGrantModel).where(
                    WeChatSubscriptionGrantModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(NotificationPreferenceModel).where(
                    NotificationPreferenceModel.user_id.in_(user_ids)
                )
            )
            await session.execute(
                delete(FollowModel).where(FollowModel.user_id.in_(user_ids))
            )
            await session.execute(delete(LiveEventModel).where(LiveEventModel.id == event_pk))
            await session.execute(delete(LiveSessionModel).where(LiveSessionModel.id == session_pk))
            await session.execute(delete(PlatformAccountModel).where(PlatformAccountModel.id == account_pk))
            await session.execute(delete(CreatorModel).where(CreatorModel.id == creator_id))
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
