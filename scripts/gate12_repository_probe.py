#!/usr/bin/env python3
"""Gate 1.2-2 real PostgreSQL bridge + repository probe.

The probe creates one isolated temporary database, migrates it first to the
accepted Gate 1.1 head, seeds representative legacy bridge facts, upgrades to
the Gate 1.2 compatibility head, proves those old facts were preserved, then
exercises all four formal SQLAlchemy repositories with new rows that deliberately
leave obsolete legacy bridge fields NULL.

The normal ``stageletter`` database is never modified.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import (
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveStatus,
    SessionOrigin,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    NotificationDelivery,
)
from stage_letter.infrastructure.db.models import (
    LiveEventModel,
    LiveObservationModel,
    LiveSessionModel,
    NotificationDeliveryModel,
    PlatformAccountModel,
)
from stage_letter.infrastructure.db.repositories import (
    SQLAlchemyCreatorRepository,
    SQLAlchemyFollowRepository,
    SQLAlchemyLiveRepository,
    SQLAlchemyNotificationRepository,
)


ROOT = Path(__file__).resolve().parents[1]
GATE11_HEAD = "b63e4f9a1c20"
EXPECTED_HEAD = "c91e8d2f4a10"
DB_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("GATE12_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GATE12_DB_PORT", "5433")))
    parser.add_argument("--user", default=os.getenv("GATE12_DB_USER", "stageletter"))
    parser.add_argument("--password", default=os.getenv("GATE12_DB_PASSWORD", "stageletter"))
    parser.add_argument("--maintenance-db", default=os.getenv("GATE12_MAINT_DB", "postgres"))
    return parser.parse_args()


def _url(args: argparse.Namespace, database: str) -> str:
    return (
        f"postgresql+asyncpg://{args.user}:{args.password}"
        f"@{args.host}:{args.port}/{database}"
    )


def _upgrade(args: argparse.Namespace, database: str, target: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _url(args, database))
    command.upgrade(cfg, target)


async def _connect(args: argparse.Namespace, database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=database,
    )


async def _drop_database(args: argparse.Namespace, database: str) -> None:
    if not DB_NAME_RE.fullmatch(database):
        raise ValueError(f"unsafe database name: {database}")
    conn = await _connect(args, args.maintenance_db)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=$1 AND pid <> pg_backend_pid()",
            database,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await conn.close()


async def _create_database(args: argparse.Namespace, database: str) -> None:
    await _drop_database(args, database)
    conn = await _connect(args, args.maintenance_db)
    try:
        await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()


async def _seed_gate11_legacy_facts(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        async with conn.transaction():
            await conn.execute("INSERT INTO users (id, openid) VALUES (1, 'gate12-legacy-user')")
            await conn.execute("INSERT INTO anchors (id, display_name) VALUES (10, 'Legacy Bridge')")
            await conn.execute("INSERT INTO creators (id) VALUES (10)")
            await conn.execute(
                """
                INSERT INTO platform_accounts (
                    id, anchor_id, creator_id, platform, platform_user_id,
                    canonical_url, last_status, is_disabled, polling_tier
                ) VALUES (
                    20, 10, 10, 'douyin', 'legacy-20',
                    'https://example.invalid/legacy', 'OFFLINE', false, 'warm'
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO live_sessions (
                    id, platform_account_id, anchor_id, platform, started_at,
                    state, started_at_source, origin
                ) VALUES (
                    40, 20, 10, 'douyin', '2026-08-19T00:00:00+00:00',
                    'CLOSED', 'platform', 'TRANSITION'
                )
                """
            )
            await conn.execute(
                """
                UPDATE live_sessions
                SET ended_at='2026-08-19T00:30:00+00:00'
                WHERE id=40
                """
            )
            await conn.execute(
                """
                INSERT INTO live_events (
                    id, event_id, platform_account_id, anchor_id, live_session_id,
                    event_type, cause, confidence, detected_at, occurred_at
                ) VALUES (
                    50, 'legacy-formal-event', 20, 10, 40,
                    'LIVE_STARTED', 'TRANSITION', 'normal',
                    '2026-08-19T00:00:10+00:00', '2026-08-19T00:00:10+00:00'
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO notification_jobs (
                    id, live_event_id, live_session_id, user_id, anchor_id,
                    state, attempt
                ) VALUES (60, 50, 40, 1, 10, 'PENDING', 0)
                """
            )
            await conn.execute(
                """
                INSERT INTO notification_deliveries (
                    id, notification_job_id, user_id, live_session_id,
                    live_event_id, channel, state, attempt, updated_at
                ) VALUES (
                    70, 60, 1, 40, 50, 'WECHAT_SUBSCRIBE', 'PENDING', 0, now()
                )
                """
            )
    finally:
        await conn.close()


async def _assert_legacy_preserved(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == EXPECTED_HEAD
        pa = await conn.fetchrow(
            "SELECT anchor_id, last_status, polling_tier FROM platform_accounts WHERE id=20"
        )
        assert dict(pa) == {"anchor_id": 10, "last_status": "OFFLINE", "polling_tier": "warm"}
        session = await conn.fetchrow(
            "SELECT anchor_id, platform, state, started_at_source FROM live_sessions WHERE id=40"
        )
        assert dict(session) == {
            "anchor_id": 10,
            "platform": "douyin",
            "state": "CLOSED",
            "started_at_source": "platform",
        }
        event = await conn.fetchrow(
            "SELECT anchor_id, confidence, detected_at FROM live_events WHERE id=50"
        )
        assert event["anchor_id"] == 10
        assert event["confidence"] == "normal"
        assert event["detected_at"] is not None
        assert await conn.fetchval(
            "SELECT notification_job_id FROM notification_deliveries WHERE id=70"
        ) == 60
    finally:
        await conn.close()


async def _exercise_repositories(args: argparse.Namespace, database: str) -> None:
    engine = create_async_engine(_url(args, database))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    try:
        # User creation is outside the four Gate 1.2 repository ports.
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO users (id, openid) VALUES (2, 'gate12-formal-user')")
            )

        async with sessions() as session:
            creators = SQLAlchemyCreatorRepository(session)
            follows = SQLAlchemyFollowRepository(session)
            live = SQLAlchemyLiveRepository(session)
            notifications = SQLAlchemyNotificationRepository(session)

            await creators.save_creator(Creator("100"))
            await session.flush()
            await creators.save_profile(
                CreatorProfile(
                    creator_id="100",
                    display_name="Formal Creator",
                    avatar_url=None,
                    bio="Gate 1.2 repository probe",
                )
            )
            await creators.save_account(
                PlatformAccount(
                    account_id="200",
                    creator_id="100",
                    platform="douyin",
                    platform_user_id="formal-200",
                    room_id="room-200",
                    canonical_url=None,
                    enabled=True,
                )
            )
            await session.flush()

            await follows.save_follow(
                Follow(user_id="2", creator_id="100", account_id="200", starred=True)
            )
            await follows.save_notification_preference(
                NotificationPreference(user_id="2", account_id="200", enabled=True)
            )

            observation = LiveObservation(
                observation_id="obs:gate12:1",
                account_id="200",
                status=LiveStatus.LIVE,
                observed_at=now,
                source="gate12-probe",
            )
            await live.append_observation(observation)
            await live.append_observation(observation)
            assert await live.has_observation("200", "gate12-probe", "obs:gate12:1")

            formal_session = LiveSession(
                session_id="300",
                account_id="200",
                opened_at=now,
                origin=SessionOrigin.TRANSITION,
            )
            await live.save_session(formal_session)
            await session.flush()

            formal_event = LiveEvent(
                event_id="event:gate12:live-started",
                account_id="200",
                session_id="300",
                event_type=LiveEventType.LIVE_STARTED,
                cause=LiveEventCause.TRANSITION,
                occurred_at=now,
            )
            await live.append_event(formal_event)
            await session.flush()

            delivery = NotificationDelivery(
                key=DeliveryKey(
                    user_id="2",
                    live_event_id="event:gate12:live-started",
                    channel=DeliveryChannel.WECHAT_SUBSCRIBE,
                ),
                account_id="200",
                session_id="300",
                created_at=now,
            )
            assert await notifications.create_delivery(delivery) is True
            assert await notifications.create_delivery(delivery) is False

            # Transaction ownership stays outside repository methods.
            await session.commit()

        async with sessions() as session:
            creators = SQLAlchemyCreatorRepository(session)
            follows = SQLAlchemyFollowRepository(session)
            live = SQLAlchemyLiveRepository(session)
            notifications = SQLAlchemyNotificationRepository(session)

            assert await creators.get_creator("100") == Creator("100")
            account = await creators.get_account("200")
            assert account is not None and account.canonical_url is None and account.enabled
            assert (await follows.get_follow("2", "200")) == Follow(
                user_id="2", creator_id="100", account_id="200", starred=True
            )
            assert (await live.get_latest_observation("200")) == observation
            assert (await live.get_open_session("200")) == formal_session
            assert (await live.get_event("event:gate12:live-started")) == formal_event
            assert await notifications.get_delivery(delivery.key) == delivery

            obs_count = await session.scalar(
                select(LiveObservationModel.id)
                .where(
                    LiveObservationModel.platform_account_id == 200,
                    LiveObservationModel.source == "gate12-probe",
                    LiveObservationModel.observation_id == "obs:gate12:1",
                )
            )
            assert obs_count is not None

            # New formal writes leave obsolete bridge facts unknown instead of fake.
            pa = await session.get(PlatformAccountModel, 200)
            ls = await session.get(LiveSessionModel, 300)
            ev = await session.scalar(
                select(LiveEventModel).where(
                    LiveEventModel.event_id == "event:gate12:live-started"
                )
            )
            nd = await session.scalar(
                select(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.user_id == 2,
                    NotificationDeliveryModel.live_event_id == ev.id,
                )
            )
            assert pa is not None and pa.legacy_anchor_id is None
            assert ls is not None
            assert ls.legacy_anchor_id is None
            assert ls.legacy_platform is None
            assert ls.legacy_state is None
            assert ls.started_at_source is None
            assert ev is not None
            assert ev.legacy_anchor_id is None
            assert ev.legacy_confidence is None
            assert ev.legacy_detected_at is None
            assert nd is not None and nd.legacy_notification_job_id is None

            duplicate_delivery_count = await session.scalar(
                text(
                    "SELECT count(*) FROM notification_deliveries "
                    "WHERE user_id=2 AND live_event_id=:event_pk "
                    "AND channel='WECHAT_SUBSCRIBE'"
                ).bindparams(event_pk=ev.id)
            )
            assert duplicate_delivery_count == 1
    finally:
        await engine.dispose()


def main() -> int:
    args = _parse_args()
    database = "stageletter_gate12_repo"
    try:
        asyncio.run(_create_database(args, database))
        print("[gate12] database created")
        _upgrade(args, database, GATE11_HEAD)
        print(f"[gate12] seeded at Gate 1.1 head -> {GATE11_HEAD}")
        asyncio.run(_seed_gate11_legacy_facts(args, database))
        _upgrade(args, database, "head")
        asyncio.run(_assert_legacy_preserved(args, database))
        print(f"[gate12] bridge migration PASS -> {EXPECTED_HEAD}")
        asyncio.run(_exercise_repositories(args, database))
        print("PASS: Gate 1.2-2 SQLAlchemy repositories + legacy write bridge")
        return 0
    finally:
        try:
            asyncio.run(_drop_database(args, database))
            print(f"[cleanup] dropped {database}")
        except Exception as exc:
            print(f"[cleanup] WARN {database}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
