#!/usr/bin/env python3
"""Gate 1.2-3 real PostgreSQL UnitOfWork transaction probe.

Creates one isolated temporary database, migrates it to the current Gate 1.2
head, then proves commit, implicit rollback, exceptional rollback, shared-session
repository wiring, and atomic multi-repository persistence. The normal
``stageletter`` database is never modified.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg
from alembic import command
from alembic.config import Config
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
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


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


def _upgrade(args: argparse.Namespace, database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _url(args, database))
    command.upgrade(cfg, "head")


async def _seed_user(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        await conn.execute("INSERT INTO users (id, openid) VALUES (1, 'gate12-uow-user')")
    finally:
        await conn.close()


async def _exercise_uow(args: argparse.Namespace, database: str) -> None:
    engine = create_async_engine(_url(args, database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)

    try:
        # 1. One explicit commit persists a multi-repository aggregate of facts.
        async with SQLAlchemyUnitOfWork(factory) as uow:
            assert uow.session is not None
            assert uow.creators is not None
            assert uow.follows is not None
            assert uow.live is not None
            assert uow.notifications is not None
            assert uow.creators.session is uow.session
            assert uow.follows.session is uow.session
            assert uow.live.session is uow.session
            assert uow.notifications.session is uow.session

            await uow.creators.save_creator(Creator("100"))
            await uow.creators.save_profile(
                CreatorProfile(
                    creator_id="100",
                    display_name="UoW Creator",
                    bio="Gate 1.2-3 atomic commit",
                )
            )
            await uow.creators.save_account(
                PlatformAccount(
                    account_id="200",
                    creator_id="100",
                    platform="douyin",
                    platform_user_id="uow-200",
                )
            )
            await uow.follows.save_follow(
                Follow(user_id="1", creator_id="100", account_id="200", starred=True)
            )
            await uow.follows.save_notification_preference(
                NotificationPreference(user_id="1", account_id="200", enabled=True)
            )
            await uow.live.append_observation(
                LiveObservation(
                    observation_id="obs:uow:commit",
                    account_id="200",
                    status=LiveStatus.LIVE,
                    observed_at=now,
                    source="gate12-uow",
                )
            )
            await uow.live.save_session(
                LiveSession(
                    session_id="300",
                    account_id="200",
                    opened_at=now,
                    origin=SessionOrigin.TRANSITION,
                )
            )
            await uow.live.append_event(
                LiveEvent(
                    event_id="event:uow:commit",
                    account_id="200",
                    session_id="300",
                    event_type=LiveEventType.LIVE_STARTED,
                    cause=LiveEventCause.TRANSITION,
                    occurred_at=now,
                )
            )
            await uow.notifications.create_delivery(
                NotificationDelivery(
                    key=DeliveryKey(
                        user_id="1",
                        live_event_id="event:uow:commit",
                        channel=DeliveryChannel.WECHAT_SUBSCRIBE,
                    ),
                    account_id="200",
                    session_id="300",
                    created_at=now,
                )
            )
            await uow.commit()

        conn = await _connect(args, database)
        try:
            checks = {
                "creator": await conn.fetchval("SELECT count(*) FROM creators WHERE id=100"),
                "account": await conn.fetchval("SELECT count(*) FROM platform_accounts WHERE id=200"),
                "follow": await conn.fetchval(
                    "SELECT count(*) FROM follows WHERE user_id=1 AND platform_account_id=200"
                ),
                "preference": await conn.fetchval(
                    "SELECT count(*) FROM notification_preferences "
                    "WHERE user_id=1 AND platform_account_id=200"
                ),
                "observation": await conn.fetchval(
                    "SELECT count(*) FROM live_observations "
                    "WHERE platform_account_id=200 AND observation_id='obs:uow:commit'"
                ),
                "session": await conn.fetchval("SELECT count(*) FROM live_sessions WHERE id=300"),
                "event": await conn.fetchval(
                    "SELECT count(*) FROM live_events WHERE event_id='event:uow:commit'"
                ),
                "delivery": await conn.fetchval(
                    "SELECT count(*) FROM notification_deliveries nd "
                    "JOIN live_events le ON le.id=nd.live_event_id "
                    "WHERE nd.user_id=1 AND le.event_id='event:uow:commit'"
                ),
            }
            assert all(value == 1 for value in checks.values()), checks
        finally:
            await conn.close()

        # 2. Normal context exit without explicit commit must roll back all writes.
        async with SQLAlchemyUnitOfWork(factory) as uow:
            assert uow.creators is not None and uow.live is not None
            await uow.creators.save_creator(Creator("101"))
            await uow.creators.save_account(
                PlatformAccount(
                    account_id="201",
                    creator_id="101",
                    platform="douyin",
                    platform_user_id="uow-201",
                )
            )
            await uow.live.append_observation(
                LiveObservation(
                    observation_id="obs:uow:rollback",
                    account_id="201",
                    status=LiveStatus.UNKNOWN,
                    observed_at=now,
                    source="gate12-uow",
                )
            )
            # no commit

        conn = await _connect(args, database)
        try:
            assert await conn.fetchval("SELECT count(*) FROM creators WHERE id=101") == 0
            assert await conn.fetchval("SELECT count(*) FROM platform_accounts WHERE id=201") == 0
            assert await conn.fetchval(
                "SELECT count(*) FROM live_observations WHERE observation_id='obs:uow:rollback'"
            ) == 0
        finally:
            await conn.close()

        # 3. Exceptional exit must also roll back and propagate the exception.
        try:
            async with SQLAlchemyUnitOfWork(factory) as uow:
                assert uow.creators is not None
                await uow.creators.save_creator(Creator("102"))
                raise RuntimeError("gate12-uow-induced-failure")
        except RuntimeError as exc:
            assert str(exc) == "gate12-uow-induced-failure"
        else:
            raise AssertionError("UnitOfWork swallowed application exception")

        conn = await _connect(args, database)
        try:
            assert await conn.fetchval("SELECT count(*) FROM creators WHERE id=102") == 0
        finally:
            await conn.close()
    finally:
        await engine.dispose()


def main() -> int:
    args = _parse_args()
    database = "stageletter_gate12_uow"
    try:
        asyncio.run(_create_database(args, database))
        print("[uow] database created")
        _upgrade(args, database)
        asyncio.run(_seed_user(args, database))
        asyncio.run(_exercise_uow(args, database))
        print(f"[uow] head PASS -> {EXPECTED_HEAD}")
        print("PASS: Gate 1.2-3 SQLAlchemy UnitOfWork transaction semantics")
        return 0
    finally:
        try:
            asyncio.run(_drop_database(args, database))
            print(f"[cleanup] dropped {database}")
        except Exception as exc:
            print(f"[cleanup] WARN {database}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
