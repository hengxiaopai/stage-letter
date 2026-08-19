#!/usr/bin/env python3
"""Gate 1.5-3 real PostgreSQL session/event persistence probe."""
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

from stage_letter.application.services.live_transition import (
    LiveTransitionPersistenceApplicationService,
)
from stage_letter.domain.live import (
    LiveEventCause,
    LiveObservation,
    LiveStatus,
    SessionOrigin,
)
from stage_letter.domain.state_engine import TransitionIntent, TransitionIntentType
from stage_letter.infrastructure.db.models import (
    LiveEventModel,
    LiveObservationModel,
    LiveSessionModel,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


EXPECTED_HEAD = "d14e7c9a5b30"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    suffix = secrets.randbelow(400_000_000) + 100_000_000
    creator_id = 7_000_000_000_000_000_000 + suffix * 2
    account_id = creator_id + 1
    account = str(account_id)
    platform_user_id = f"gate15-{secrets.token_hex(8)}"
    opened_at = datetime.now(timezone.utc).replace(microsecond=0)
    source_started_at = opened_at - timedelta(minutes=2)
    closed_at = opened_at + timedelta(minutes=30)
    open_observation = LiveObservation(
        observation_id=f"monitor:gate15-open-{secrets.token_hex(12)}",
        account_id=account,
        status=LiveStatus.LIVE,
        observed_at=opened_at,
        source="gate15.probe.live",
        source_started_at=source_started_at,
    )
    close_observation = LiveObservation(
        observation_id=f"monitor:gate15-close-{secrets.token_hex(12)}",
        account_id=account,
        status=LiveStatus.OFFLINE,
        observed_at=closed_at,
        source="gate15.probe.offline",
    )

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if head != EXPECTED_HEAD:
        print(json.dumps({
            "gate": "1.5-3",
            "status": "BLOCKED",
            "reason": "migration head mismatch",
            "expected_head": EXPECTED_HEAD,
            "observed_head": head,
            "production_approved": False,
        }, indent=2))
        await engine.dispose()
        return 2

    async with engine.begin() as connection:
        await connection.execute(text("INSERT INTO creators (id) VALUES (:id)"), {"id": creator_id})
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
            {"id": account_id, "creator_id": creator_id, "platform_user_id": platform_user_id},
        )

    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(sessions)

    try:
        async with uow_factory() as uow:
            assert uow.live is not None
            await uow.live.append_observation(open_observation)
            await uow.live.append_observation(close_observation)
            await uow.commit()

        service = LiveTransitionPersistenceApplicationService(uow_factory)
        open_intent = TransitionIntent(
            intent_type=TransitionIntentType.OPEN_SESSION,
            occurred_at=opened_at,
            cause=LiveEventCause.TRANSITION,
            origin=SessionOrigin.TRANSITION,
            source_started_at=source_started_at,
        )
        close_intent = TransitionIntent(
            intent_type=TransitionIntentType.CLOSE_SESSION,
            occurred_at=closed_at,
            cause=LiveEventCause.TRANSITION,
        )

        opened = await service.apply(open_observation, open_intent)
        replayed_open = await service.apply(open_observation, open_intent)
        closed = await service.apply(close_observation, close_intent)

        async with engine.connect() as connection:
            session_count = await connection.scalar(
                select(func.count()).select_from(LiveSessionModel).where(
                    LiveSessionModel.platform_account_id == account_id
                )
            )
            event_count = await connection.scalar(
                select(func.count()).select_from(LiveEventModel).where(
                    LiveEventModel.platform_account_id == account_id
                )
            )
            open_count = await connection.scalar(
                select(func.count()).select_from(LiveSessionModel).where(
                    LiveSessionModel.platform_account_id == account_id,
                    LiveSessionModel.closed_at.is_(None),
                )
            )
            stored_session = await connection.execute(
                select(
                    LiveSessionModel.id,
                    LiveSessionModel.opened_at,
                    LiveSessionModel.closed_at,
                    LiveSessionModel.origin,
                    LiveSessionModel.source_started_at,
                ).where(LiveSessionModel.platform_account_id == account_id)
            )
            row = stored_session.one()

        passed = (
            opened.session.session_id == replayed_open.session.session_id
            and replayed_open.reused_existing
            and closed.session.session_id == opened.session.session_id
            and session_count == 1
            and event_count == 2
            and open_count == 0
            and str(row.id) == opened.session.session_id
            and row.closed_at == closed_at
            and row.origin == SessionOrigin.TRANSITION.value
            and row.source_started_at == source_started_at
        )

        print(json.dumps({
            "gate": "1.5-3",
            "status": "PASS" if passed else "FAIL",
            "migration_head": EXPECTED_HEAD,
            "session_id": opened.session.session_id,
            "session_id_database_allocated": opened.session.session_id.isdecimal(),
            "open_replay_reused_existing": replayed_open.reused_existing,
            "same_session_closed": closed.session.session_id == opened.session.session_id,
            "session_count": session_count,
            "event_count": event_count,
            "open_session_count_after_close": open_count,
            "provider_called": False,
            "notification_created": False,
            "production_approved": False,
        }, indent=2))
        return 0 if passed else 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(LiveEventModel).where(LiveEventModel.platform_account_id == account_id)
            )
            await connection.execute(
                delete(LiveSessionModel).where(LiveSessionModel.platform_account_id == account_id)
            )
            await connection.execute(
                delete(LiveObservationModel).where(LiveObservationModel.platform_account_id == account_id)
            )
            await connection.execute(text("DELETE FROM platform_accounts WHERE id = :id"), {"id": account_id})
            await connection.execute(text("DELETE FROM creators WHERE id = :id"), {"id": creator_id})
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
