#!/usr/bin/env python3
"""Gate 2.5 controlled PostgreSQL restart/multi-worker/capacity acceptance.

No provider or notification call is made. The probe chooses a platform account
without an existing detection lease, races two independent DB sessions for one
lease, verifies restart visibility and expired takeover, then removes its lease.
It also runs an in-memory cross-platform capacity isolation check.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.infrastructure.detection.leases import SQLAlchemyDetectionLeaseRepository
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
)
from workers.monitoring.scheduler import make_probe_id

EXPECTED_HEAD = "b25d4e9c7a12"
LEASE_SECONDS = 30


async def _capacity_check() -> dict[str, object]:
    policy = PlatformRuntimePolicy(
        max_global_concurrency=2,
        max_platform_concurrency=1,
        requests_per_second=1_000_000,
        max_attempts=1,
    )
    coordinator = DetectionRuntimeCoordinator(default_policy=policy)
    first_douyin_started = asyncio.Event()
    bilibili_started = asyncio.Event()
    release_douyin = asyncio.Event()
    douyin_calls = 0

    async def douyin_operation() -> str:
        nonlocal douyin_calls
        douyin_calls += 1
        if douyin_calls == 1:
            first_douyin_started.set()
            await release_douyin.wait()
        return "douyin-ok"

    async def bilibili_operation() -> str:
        bilibili_started.set()
        return "bilibili-ok"

    douyin_tasks = [
        asyncio.create_task(coordinator.execute("douyin", douyin_operation))
        for _ in range(6)
    ]
    await asyncio.wait_for(first_douyin_started.wait(), timeout=2.0)
    bilibili_task = asyncio.create_task(
        coordinator.execute("bilibili", bilibili_operation)
    )
    healthy_platform_progressed = False
    try:
        await asyncio.wait_for(bilibili_started.wait(), timeout=1.0)
        healthy_platform_progressed = True
    finally:
        release_douyin.set()

    outcomes = await asyncio.gather(*douyin_tasks, bilibili_task)
    return {
        "global_limit": policy.max_global_concurrency,
        "per_platform_limit": policy.max_platform_concurrency,
        "saturated_platform": "douyin",
        "healthy_platform": "bilibili",
        "healthy_platform_progressed_while_douyin_blocked": healthy_platform_progressed,
        "all_capacity_operations_succeeded": all(item.succeeded for item in outcomes),
        "operation_count": len(outcomes),
    }


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    account_id: int | None = None
    initial_lease_count = 0
    cleanup_performed = False
    winner_owner: str | None = None
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if head != EXPECTED_HEAD:
                print(
                    json.dumps(
                        {
                            "gate": "2.5",
                            "probe": "postgresql_restart_multiworker_capacity",
                            "status": "BLOCKED",
                            "reason": "database migration head is not Gate 2.5; run alembic upgrade head",
                            "migration_head": head,
                            "expected_head": EXPECTED_HEAD,
                            "provider_called": False,
                            "notification_called": False,
                            "database_write_performed": False,
                        },
                        indent=2,
                    )
                )
                return 2
            row = (
                await connection.execute(
                    text(
                        "SELECT pa.id, pa.platform "
                        "FROM platform_accounts pa "
                        "WHERE NOT EXISTS ("
                        "  SELECT 1 FROM detection_probe_leases l "
                        "  WHERE l.platform_account_id=pa.id"
                        ") "
                        "ORDER BY pa.is_disabled DESC, pa.id ASC LIMIT 1"
                    )
                )
            ).mappings().one_or_none()
            if row is None:
                raise RuntimeError("no platform account without an active detection lease is available")
            account_id = int(row["id"])
            platform = str(row["platform"])
            initial_lease_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM detection_probe_leases "
                        "WHERE platform_account_id=:account_id"
                    ),
                    {"account_id": account_id},
                )
                or 0
            )

        repo_a = SQLAlchemyDetectionLeaseRepository(factory)
        repo_b = SQLAlchemyDetectionLeaseRepository(factory)
        now = datetime.now(timezone.utc)
        probe_id = make_probe_id("gate25-controlled-race", str(account_id))
        owner_a = "gate25-worker-a"
        owner_b = "gate25-worker-b"

        race = await asyncio.gather(
            repo_a.try_acquire(
                account_id=str(account_id),
                probe_id=probe_id,
                owner_token=owner_a,
                now=now,
                lease_seconds=LEASE_SECONDS,
            ),
            repo_b.try_acquire(
                account_id=str(account_id),
                probe_id=probe_id,
                owner_token=owner_b,
                now=now,
                lease_seconds=LEASE_SECONDS,
            ),
        )
        acquired = [item for item in race if item.acquired]
        race_acquired_count = len(acquired)
        if acquired:
            assert acquired[0].lease is not None
            winner_owner = acquired[0].lease.owner_token

        # A fresh engine represents another worker/process after restart. A live
        # lease must still be visible and block provider execution.
        await engine.dispose()
        restart_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        restart_factory = async_sessionmaker(restart_engine, expire_on_commit=False)
        restart_repo = SQLAlchemyDetectionLeaseRepository(restart_factory)
        try:
            before_expiry = await restart_repo.try_acquire(
                account_id=str(account_id),
                probe_id=make_probe_id("gate25-after-restart", str(account_id)),
                owner_token="gate25-worker-restart",
                now=now + timedelta(seconds=1),
                lease_seconds=LEASE_SECONDS,
            )
            expired_takeover = await restart_repo.try_acquire(
                account_id=str(account_id),
                probe_id=make_probe_id("gate25-expired-takeover", str(account_id)),
                owner_token="gate25-worker-takeover",
                now=now + timedelta(seconds=LEASE_SECONDS + 1),
                lease_seconds=LEASE_SECONDS,
            )
            non_owner_release = await restart_repo.release(
                account_id=str(account_id),
                owner_token=winner_owner or "gate25-no-winner",
            )
            owner_release = await restart_repo.release(
                account_id=str(account_id),
                owner_token="gate25-worker-takeover",
            )

            async with restart_engine.connect() as connection:
                final_lease_count = int(
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM detection_probe_leases "
                            "WHERE platform_account_id=:account_id"
                        ),
                        {"account_id": account_id},
                    )
                    or 0
                )
            cleanup_performed = owner_release
        finally:
            await restart_engine.dispose()

        capacity = await _capacity_check()
        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "account_started_without_lease": initial_lease_count == 0,
            "concurrent_race_single_winner": race_acquired_count == 1,
            "restart_preserved_live_lease": before_expiry.acquired is False,
            "expired_lease_takeover": expired_takeover.acquired is True,
            "old_owner_cannot_release_takeover": non_owner_release is False,
            "takeover_owner_released": owner_release is True,
            "lease_cleanup_complete": final_lease_count == 0,
            "healthy_platform_progressed_under_saturation": bool(
                capacity["healthy_platform_progressed_while_douyin_blocked"]
            ),
            "capacity_operations_succeeded": bool(
                capacity["all_capacity_operations_succeeded"]
            ),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        payload = {
            "gate": "2.5",
            "probe": "postgresql_restart_multiworker_capacity",
            "status": status,
            "migration_head": head,
            "account_id": str(account_id),
            "platform": platform,
            "lease_seconds": LEASE_SECONDS,
            "concurrent_race_acquired_count": race_acquired_count,
            "restart_live_lease_acquired_by_second_worker": before_expiry.acquired,
            "expired_takeover_acquired": expired_takeover.acquired,
            "non_owner_release_succeeded": non_owner_release,
            "takeover_owner_release_succeeded": owner_release,
            "capacity": capacity,
            "checks": checks,
            "provider_called": False,
            "notification_called": False,
            "database_write_performed": True,
            "cleanup_performed": cleanup_performed,
            "database_restored": final_lease_count == initial_lease_count == 0,
            "live_truth_mutated": False,
            "gate0a_lifecycle_claimed": False,
            "worker_exactly_once_claimed": False,
            "provider_exactly_once_claimed": False,
            "production_approved": False,
        }
        print(json.dumps(payload, indent=2))
        return 0 if status == "PASS" else 1
    finally:
        # Best-effort cleanup only for this probe's owner tokens. Never delete an
        # unrelated live worker's lease.
        if account_id is not None:
            try:
                cleanup_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
                async with cleanup_engine.begin() as connection:
                    await connection.execute(
                        text(
                            "DELETE FROM detection_probe_leases "
                            "WHERE platform_account_id=:account_id "
                            "AND owner_token LIKE 'gate25-worker-%'"
                        ),
                        {"account_id": account_id},
                    )
                await cleanup_engine.dispose()
            except Exception:
                pass
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
