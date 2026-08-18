#!/usr/bin/env python3
"""Gate 1.1-5 real PostgreSQL migration probe.

Runs two isolated temporary databases against the local Stage Letter PostgreSQL:

1. CLEAN: empty database -> Alembic head.
2. LEGACY: migrate to pre-Gate-1 head, seed representative persisted facts,
   then migrate to current head and verify deterministic backfills + constraints.

The probe never touches the normal ``stageletter`` database. Temporary databases
are dropped in ``finally`` even when validation fails.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
PRE_GATE1_HEAD = "e98c1011d830"
EXPECTED_HEAD = "b63e4f9a1c20"
DB_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _db_url(args: argparse.Namespace, database: str) -> str:
    return (
        f"postgresql+asyncpg://{args.user}:{args.password}"
        f"@{args.host}:{args.port}/{database}"
    )


def _alembic_upgrade(args: argparse.Namespace, database: str, target: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _db_url(args, database))
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
    if not DB_NAME_RE.match(database):
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
    if not DB_NAME_RE.match(database):
        raise ValueError(f"unsafe database name: {database}")
    await _drop_database(args, database)
    conn = await _connect(args, args.maintenance_db)
    try:
        await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()


async def _version(args: argparse.Namespace, database: str) -> str:
    conn = await _connect(args, database)
    try:
        return await conn.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()


async def _validate_clean(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        assert version == EXPECTED_HEAD, (version, EXPECTED_HEAD)

        tables = {
            row["tablename"]
            for row in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        }
        required = {
            "users",
            "creators",
            "creator_profiles",
            "platform_accounts",
            "follows",
            "notification_preferences",
            "live_observations",
            "live_sessions",
            "live_events",
            "notification_deliveries",
        }
        missing = required - tables
        assert not missing, f"missing formal tables: {sorted(missing)}"

        constraint_names = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE connamespace='public'::regnamespace"
            )
        }
        for name in {
            "ck_g11_live_observation_status",
            "ck_g11_live_session_origin",
            "uq_g11_live_event_id",
            "ck_g11_live_event_cause",
            "uq_g11_delivery_user_event_channel",
        }:
            assert name in constraint_names, f"missing constraint: {name}"

        index_names = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
            )
        }
        assert "uq_g11_open_session_per_account" in index_names
    finally:
        await conn.close()


async def _seed_legacy(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO users (id, openid) VALUES (1, 'gate11-openid')"
            )
            await conn.execute(
                "INSERT INTO anchors (id, display_name) VALUES (10, 'Gate11 Creator')"
            )
            await conn.execute(
                """
                INSERT INTO platform_accounts (
                    id, anchor_id, platform, platform_user_id, canonical_url,
                    last_status, is_disabled, polling_tier
                ) VALUES (
                    20, 10, 'douyin', 'gate11-user', 'https://example.invalid/live',
                    'OFFLINE', false, 'warm'
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO user_subscriptions (
                    id, user_id, anchor_id, platform_account_id,
                    notify_enabled, is_starred
                ) VALUES (30, 1, 10, 20, true, true)
                """
            )
            await conn.execute(
                """
                INSERT INTO live_sessions (
                    id, platform_account_id, anchor_id, platform, started_at,
                    state, started_at_source
                ) VALUES (
                    40, 20, 10, 'douyin', '2026-08-18T12:00:00+00:00',
                    'OPEN', 'platform'
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO live_events (
                    id, platform_account_id, anchor_id, live_session_id,
                    event_type, confidence, detected_at
                ) VALUES (
                    50, 20, 10, 40, 'CONFIRMED_ONLINE', 'normal',
                    '2026-08-18T12:00:10+00:00'
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
                    channel, state, attempt
                ) VALUES (70, 60, 1, 40, 'wechat', 'PENDING', 0)
                """
            )
    finally:
        await conn.close()


async def _validate_legacy(args: argparse.Namespace, database: str) -> None:
    conn = await _connect(args, database)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == EXPECTED_HEAD

        creator = await conn.fetchrow("SELECT id FROM creators WHERE id=10")
        profile = await conn.fetchrow(
            "SELECT creator_id, display_name FROM creator_profiles WHERE creator_id=10"
        )
        assert creator and creator["id"] == 10
        assert profile and profile["display_name"] == "Gate11 Creator"

        assert await conn.fetchval(
            "SELECT creator_id FROM platform_accounts WHERE id=20"
        ) == 10
        assert await conn.fetchval(
            "SELECT count(*) FROM follows WHERE user_id=1 AND platform_account_id=20"
        ) == 1
        assert await conn.fetchval(
            "SELECT count(*) FROM notification_preferences "
            "WHERE user_id=1 AND platform_account_id=20 AND enabled=true"
        ) == 1

        # Gate 1 never fabricates historical observations.
        assert await conn.fetchval("SELECT count(*) FROM live_observations") == 0

        session = await conn.fetchrow(
            "SELECT started_at, source_started_at, origin FROM live_sessions WHERE id=40"
        )
        assert session["source_started_at"] == session["started_at"]
        assert session["origin"] is None

        event = await conn.fetchrow(
            "SELECT event_id, cause, detected_at, occurred_at FROM live_events WHERE id=50"
        )
        assert event["event_id"] is None
        assert event["cause"] is None
        assert event["occurred_at"] == event["detected_at"]

        delivery = await conn.fetchrow(
            "SELECT live_event_id, channel, updated_at FROM notification_deliveries WHERE id=70"
        )
        assert delivery["live_event_id"] == 50
        assert delivery["channel"] == "WECHAT_SUBSCRIBE"
        assert delivery["updated_at"] is not None

        # DB constraint: canonical observation vocabulary only.
        try:
            await conn.execute(
                """
                INSERT INTO live_observations (
                    observation_id, platform_account_id, status, observed_at, source
                ) VALUES ('bad-status', 20, 'ONLINE', now(), 'gate11')
                """
            )
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError("invalid canonical observation status was accepted")

        # DB constraint: ended_at NULL is the formal open-session invariant,
        # independent of the legacy state column.
        try:
            await conn.execute(
                """
                INSERT INTO live_sessions (
                    id, platform_account_id, anchor_id, platform, started_at,
                    state, started_at_source, ended_at
                ) VALUES (
                    41, 20, 10, 'douyin', '2026-08-18T13:00:00+00:00',
                    'CLOSED', 'probe', NULL
                )
                """
            )
        except asyncpg.UniqueViolationError:
            pass
        else:
            raise AssertionError("second ended_at=NULL session was accepted")

        # DB constraint: one logical delivery per user/event/channel.
        try:
            await conn.execute(
                """
                INSERT INTO notification_deliveries (
                    id, notification_job_id, user_id, live_session_id,
                    live_event_id, channel, state, attempt, updated_at
                ) VALUES (
                    71, 60, 1, NULL, 50, 'WECHAT_SUBSCRIBE', 'PENDING', 0, now()
                )
                """
            )
        except asyncpg.UniqueViolationError:
            pass
        else:
            raise AssertionError("duplicate logical delivery was accepted")
    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("GATE11_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GATE11_DB_PORT", "5433")))
    parser.add_argument("--user", default=os.getenv("GATE11_DB_USER", "stageletter"))
    parser.add_argument("--password", default=os.getenv("GATE11_DB_PASSWORD", "stageletter"))
    parser.add_argument("--maintenance-db", default=os.getenv("GATE11_MAINT_DB", "postgres"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    clean_db = "stageletter_gate11_clean"
    legacy_db = "stageletter_gate11_legacy"

    try:
        asyncio.run(_create_database(args, clean_db))
        print("[clean] database created")
        _alembic_upgrade(args, clean_db, "head")
        asyncio.run(_validate_clean(args, clean_db))
        print(f"[clean] PASS -> {asyncio.run(_version(args, clean_db))}")

        asyncio.run(_create_database(args, legacy_db))
        print("[legacy] database created")
        _alembic_upgrade(args, legacy_db, PRE_GATE1_HEAD)
        asyncio.run(_seed_legacy(args, legacy_db))
        print("[legacy] representative fixture seeded")
        _alembic_upgrade(args, legacy_db, "head")
        asyncio.run(_validate_legacy(args, legacy_db))
        print(f"[legacy] PASS -> {asyncio.run(_version(args, legacy_db))}")

        print("PASS: Gate 1.1-5 clean + legacy PostgreSQL migration probe")
        return 0
    finally:
        for database in (clean_db, legacy_db):
            try:
                asyncio.run(_drop_database(args, database))
                print(f"[cleanup] dropped {database}")
            except Exception as exc:  # cleanup evidence, then preserve original failure
                print(f"[cleanup] WARN {database}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
