#!/usr/bin/env python3
"""Gate 1.4-5 real PostgreSQL observation durability probe.

This script is intentionally runnable directly from the repository root with
``python scripts/gate14_observation_durability_probe.py``. It validates the
formal monitor-probe durable identity across independent DB sessions and an
engine restart boundary. It does not claim provider exactly-once execution.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.db.models import LiveObservationModel
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


EXPECTED_HEAD = "d14e7c9a5b30"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    suffix = secrets.randbelow(900_000_000) + 100_000_000
    creator_id = 8_000_000_000_000_000_000 + suffix * 2
    account_id = creator_id + 1
    probe_id = f"monitor:gate14-durability-{secrets.token_hex(12)}"
    platform_user_id = f"gate14-{secrets.token_hex(8)}"
    observed_at = datetime.now(timezone.utc)

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if head != EXPECTED_HEAD:
        print(
            json.dumps(
                {
                    "gate": "1.4-5",
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
                "platform_user_id": platform_user_id,
            },
        )

    async def compete(source: str, status: LiveStatus) -> bool:
        observation = LiveObservation(
            observation_id=probe_id,
            account_id=str(account_id),
            status=status,
            observed_at=observed_at,
            source=source,
        )
        async with sessions() as session:
            repo = SQLAlchemyLiveRepository(session)
            inserted = await repo.append_observation(observation)
            await session.commit()
            return inserted

    try:
        inserted = await asyncio.gather(
            compete("gate14.race.a", LiveStatus.LIVE),
            compete("gate14.race.b", LiveStatus.OFFLINE),
        )

        async with engine.connect() as connection:
            row_count = await connection.scalar(
                select(func.count())
                .select_from(LiveObservationModel)
                .where(
                    LiveObservationModel.platform_account_id == account_id,
                    LiveObservationModel.observation_id == probe_id,
                )
            )

        # Dispose and recreate the engine to prove the durable winner survives a
        # runtime restart boundary rather than living only in an ORM/session cache.
        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)

        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(
                        LiveObservationModel.source,
                        LiveObservationModel.status,
                    ).where(
                        LiveObservationModel.platform_account_id == account_id,
                        LiveObservationModel.observation_id == probe_id,
                    )
                )
            ).all()

        passed = sorted(inserted) == [False, True] and row_count == 1 and len(rows) == 1
        print(
            json.dumps(
                {
                    "gate": "1.4-5",
                    "status": "PASS" if passed else "FAIL",
                    "migration_head": EXPECTED_HEAD,
                    "probe_id": probe_id,
                    "independent_session_insert_results": inserted,
                    "row_count_after_race": row_count,
                    "row_count_after_engine_restart": len(rows),
                    "durable_winner_source": rows[0][0] if rows else None,
                    "durable_winner_status": rows[0][1] if rows else None,
                    "provider_exactly_once_claimed": False,
                    "production_approved": False,
                },
                indent=2,
            )
        )
        return 0 if passed else 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(LiveObservationModel).where(
                    LiveObservationModel.platform_account_id == account_id,
                    LiveObservationModel.observation_id == probe_id,
                )
            )
            await connection.execute(
                text("DELETE FROM platform_accounts WHERE id = :id"),
                {"id": account_id},
            )
            await connection.execute(
                text("DELETE FROM creators WHERE id = :id"),
                {"id": creator_id},
            )
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
