#!/usr/bin/env python3
"""Gate 1.5-5 real PostgreSQL restart/concurrency acceptance probe.

This probe exercises the complete formal observation-consumption path. It proves
idempotent canonical state output across concurrent consumption and runtime
restart; it deliberately does not claim exactly-once worker/provider execution.
"""
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

from stage_letter.domain.live import LiveEventType, LiveObservation, LiveStatus
from stage_letter.domain.state_engine import EngineState
from stage_letter.infrastructure.db.models import (
    LiveEventModel,
    LiveObservationModel,
    LiveSessionModel,
)
from workers.composition import build_worker_services


EXPECTED_HEAD = "d14e7c9a5b30"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter"


def _database_url() -> str:
    return os.environ.get("STAGE_LETTER_DATABASE_URL", DEFAULT_DATABASE_URL)


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
        source="gate15.restart-concurrency",
        source_started_at=source_started_at,
    )


async def _counts(engine, account_pk: int) -> tuple[int, int, int, int, int]:
    async with engine.connect() as connection:
        session_count = await connection.scalar(
            select(func.count()).select_from(LiveSessionModel).where(
                LiveSessionModel.platform_account_id == account_pk
            )
        )
        event_count = await connection.scalar(
            select(func.count()).select_from(LiveEventModel).where(
                LiveEventModel.platform_account_id == account_pk
            )
        )
        open_count = await connection.scalar(
            select(func.count()).select_from(LiveSessionModel).where(
                LiveSessionModel.platform_account_id == account_pk,
                LiveSessionModel.closed_at.is_(None),
            )
        )
        start_count = await connection.scalar(
            select(func.count()).select_from(LiveEventModel).where(
                LiveEventModel.platform_account_id == account_pk,
                LiveEventModel.event_type == LiveEventType.LIVE_STARTED.value,
            )
        )
        end_count = await connection.scalar(
            select(func.count()).select_from(LiveEventModel).where(
                LiveEventModel.platform_account_id == account_pk,
                LiveEventModel.event_type == LiveEventType.LIVE_ENDED.value,
            )
        )
    return (
        int(session_count or 0),
        int(event_count or 0),
        int(open_count or 0),
        int(start_count or 0),
        int(end_count or 0),
    )


async def _main() -> int:
    database_url = _database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    suffix = secrets.randbelow(350_000_000) + 100_000_000
    creator_id = 6_000_000_000_000_000_000 + suffix * 2
    account_pk = creator_id + 1
    account_id = str(account_pk)
    platform_user_id = f"gate15-restart-{secrets.token_hex(8)}"

    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    observations = (
        _observation(
            f"monitor:gate15-r0-{secrets.token_hex(10)}",
            account_id,
            LiveStatus.OFFLINE,
            t0,
        ),
        _observation(
            f"monitor:gate15-r1-{secrets.token_hex(10)}",
            account_id,
            LiveStatus.LIVE,
            t0 + timedelta(minutes=1),
            source_started_at=t0 - timedelta(minutes=5),
        ),
        _observation(
            f"monitor:gate15-r2-{secrets.token_hex(10)}",
            account_id,
            LiveStatus.LIVE,
            t0 + timedelta(minutes=2),
            source_started_at=t0 - timedelta(minutes=5),
        ),
        _observation(
            f"monitor:gate15-r3-{secrets.token_hex(10)}",
            account_id,
            LiveStatus.OFFLINE,
            t0 + timedelta(minutes=30),
        ),
        _observation(
            f"monitor:gate15-r4-{secrets.token_hex(10)}",
            account_id,
            LiveStatus.OFFLINE,
            t0 + timedelta(minutes=31),
        ),
    )

    async with engine.connect() as connection:
        head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if head != EXPECTED_HEAD:
        print(
            json.dumps(
                {
                    "gate": "1.5-5",
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
                "id": account_pk,
                "creator_id": creator_id,
                "platform_user_id": platform_user_id,
            },
        )

    try:
        bundle = build_worker_services(sessions)

        # Persist only the history required to make observation[2] the decisive
        # OFFLINE -> LIVE transition. The target is then consumed concurrently.
        for observation in observations[:3]:
            await bundle.live_observations.record(observation)

        concurrent_results = await asyncio.gather(
            bundle.live_observation_consumer.consume(
                account_id,
                observations[2].observation_id,
            ),
            bundle.live_observation_consumer.consume(
                account_id,
                observations[2].observation_id,
            ),
        )
        concurrent_transitions = [result.transition for result in concurrent_results]
        concurrent_reused = [
            transition.reused_existing if transition is not None else None
            for transition in concurrent_transitions
        ]
        concurrent_session_ids = [
            transition.session.session_id if transition is not None else None
            for transition in concurrent_transitions
        ]
        concurrent_event_ids = [
            transition.event.event_id if transition is not None else None
            for transition in concurrent_transitions
        ]

        open_reconstruction = await bundle.state_reconstruction.reconstruct(account_id)
        open_counts = await _counts(engine, account_pk)
        open_state_matches_db = (
            open_reconstruction.snapshot.state is EngineState.LIVE_CONFIRMED
            and open_reconstruction.snapshot.session_open
            and open_counts == (1, 1, 1, 1, 0)
        )

        # Destroy the first runtime boundary and prove retry reconstruction from
        # durable truth reuses the canonical winner after restart.
        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        restarted_bundle = build_worker_services(sessions)

        restart_open = await restarted_bundle.live_observation_consumer.consume(
            account_id,
            observations[2].observation_id,
        )
        restart_open_reconstruction = await restarted_bundle.state_reconstruction.reconstruct(
            account_id
        )
        restart_open_counts = await _counts(engine, account_pk)

        # Add the two explicit OFFLINE observations. The first is pending/read-only;
        # the second is the decisive close and must close the original session.
        for observation in observations[3:]:
            await restarted_bundle.live_observations.record(observation)

        first_offline = await restarted_bundle.live_observation_consumer.consume(
            account_id,
            observations[3].observation_id,
        )
        closed = await restarted_bundle.live_observation_consumer.consume(
            account_id,
            observations[4].observation_id,
        )

        await engine.dispose()
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        final_bundle = build_worker_services(sessions)

        restart_close = await final_bundle.live_observation_consumer.consume(
            account_id,
            observations[4].observation_id,
        )
        final_reconstruction = await final_bundle.state_reconstruction.reconstruct(account_id)
        final_counts = await _counts(engine, account_pk)

        open_transition = concurrent_transitions[0]
        other_open_transition = concurrent_transitions[1]
        close_transition = closed.transition
        restart_close_transition = restart_close.transition

        passed = all(
            (
                sorted(concurrent_reused, key=lambda value: str(value)) == [False, True],
                open_transition is not None,
                other_open_transition is not None,
                len(set(concurrent_session_ids)) == 1,
                len(set(concurrent_event_ids)) == 1,
                open_state_matches_db,
                restart_open.transition is not None,
                restart_open.transition.reused_existing,
                restart_open_reconstruction.snapshot.state is EngineState.LIVE_CONFIRMED,
                restart_open_reconstruction.snapshot.session_open,
                restart_open_counts == (1, 1, 1, 1, 0),
                not first_offline.emitted_transition,
                close_transition is not None,
                open_transition is not None
                and close_transition.session.session_id == open_transition.session.session_id,
                restart_close_transition is not None,
                restart_close_transition.reused_existing,
                final_reconstruction.snapshot.state is EngineState.OFFLINE_CONFIRMED,
                not final_reconstruction.snapshot.session_open,
                final_counts == (1, 2, 0, 1, 1),
            )
        )

        print(
            json.dumps(
                {
                    "gate": "1.5-5",
                    "status": "PASS" if passed else "FAIL",
                    "migration_head": EXPECTED_HEAD,
                    "concurrent_open_reused_flags": concurrent_reused,
                    "concurrent_same_session": len(set(concurrent_session_ids)) == 1,
                    "concurrent_same_event": len(set(concurrent_event_ids)) == 1,
                    "open_state_after_concurrency": open_reconstruction.snapshot.state.value,
                    "open_state_matches_db": open_state_matches_db,
                    "session_count_after_open": open_counts[0],
                    "event_count_after_open": open_counts[1],
                    "open_session_count_after_open": open_counts[2],
                    "restart_open_reused_existing": (
                        restart_open.transition.reused_existing
                        if restart_open.transition is not None
                        else False
                    ),
                    "first_offline_read_only": not first_offline.emitted_transition,
                    "same_session_closed": (
                        close_transition is not None
                        and open_transition is not None
                        and close_transition.session.session_id
                        == open_transition.session.session_id
                    ),
                    "restart_close_reused_existing": (
                        restart_close_transition.reused_existing
                        if restart_close_transition is not None
                        else False
                    ),
                    "final_state": final_reconstruction.snapshot.state.value,
                    "final_state_matches_db": (
                        final_reconstruction.snapshot.state is EngineState.OFFLINE_CONFIRMED
                        and not final_reconstruction.snapshot.session_open
                        and final_counts == (1, 2, 0, 1, 1)
                    ),
                    "final_session_count": final_counts[0],
                    "final_event_count": final_counts[1],
                    "final_open_session_count": final_counts[2],
                    "final_live_started_count": final_counts[3],
                    "final_live_ended_count": final_counts[4],
                    "worker_exactly_once_claimed": False,
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
                delete(LiveEventModel).where(LiveEventModel.platform_account_id == account_pk)
            )
            await connection.execute(
                delete(LiveSessionModel).where(LiveSessionModel.platform_account_id == account_pk)
            )
            await connection.execute(
                delete(LiveObservationModel).where(
                    LiveObservationModel.platform_account_id == account_pk
                )
            )
            await connection.execute(
                text("DELETE FROM platform_accounts WHERE id = :id"),
                {"id": account_pk},
            )
            await connection.execute(
                text("DELETE FROM creators WHERE id = :id"),
                {"id": creator_id},
            )
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
