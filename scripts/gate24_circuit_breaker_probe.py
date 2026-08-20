#!/usr/bin/env python3
"""Gate 2.4 controlled PostgreSQL circuit-breaker acceptance.

Temporarily exercises platform_health state transitions, performs no provider or
notification call, and restores the original operational row exactly afterward.
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
from stage_letter.detection.contracts import PlatformHealthState
from stage_letter.detection.health import CircuitBreakerPolicy
from stage_letter.infrastructure.detection.health import SQLAlchemyDetectionHealthRepository

EXPECTED_HEAD = "a63f4b2d9e71"


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    original = None
    platform = None
    restored = False
    now = datetime.now(timezone.utc)
    policy = CircuitBreakerPolicy()
    states: dict[str, str] = {}
    try:
        async with engine.begin() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            platform = await connection.scalar(
                text(
                    "SELECT platform FROM platform_accounts "
                    "WHERE is_disabled=false ORDER BY id LIMIT 1"
                )
            )
            if platform is None:
                print(json.dumps({"gate": "2.4", "status": "BLOCKED", "reason": "no enabled platform account"}, ensure_ascii=False, indent=2))
                return 2
            original = (
                await connection.execute(
                    text("SELECT * FROM platform_health WHERE platform=:platform"),
                    {"platform": platform},
                )
            ).mappings().one_or_none()
            if original is not None:
                original = dict(original)

            await connection.execute(
                text(
                    "INSERT INTO platform_health "
                    "(platform,state,last_success_at,last_failure_at,success_rate_24h,avg_latency_ms_24h,"
                    "consecutive_failures,error_count_24h,success_count_24h,sustained_qps,max_anchors,updated_at) "
                    "VALUES (:platform,'HEALTHY',NULL,NULL,NULL,NULL,4,0,0,NULL,NULL,:updated_at) "
                    "ON CONFLICT (platform) DO UPDATE SET "
                    "state='HEALTHY', consecutive_failures=4, updated_at=:updated_at"
                ),
                {"platform": platform, "updated_at": now},
            )

        repository = SQLAlchemyDetectionHealthRepository(session_factory)
        first = await repository.apply_probe_outcome(
            platform=platform,
            success=False,
            at=now + timedelta(seconds=1),
            policy=policy,
        )
        states["failure_4"] = first.state.value

        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE platform_health SET state='HEALTHY', consecutive_failures=5 WHERE platform=:platform"),
                {"platform": platform},
            )
        degraded = await repository.apply_probe_outcome(
            platform=platform,
            success=False,
            at=now + timedelta(seconds=2),
            policy=policy,
        )
        states["failure_5"] = degraded.state.value

        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE platform_health SET state='DEGRADED', consecutive_failures=20 WHERE platform=:platform"),
                {"platform": platform},
            )
        disabled = await repository.apply_probe_outcome(
            platform=platform,
            success=False,
            at=now + timedelta(seconds=3),
            policy=policy,
        )
        states["failure_20"] = disabled.state.value

        sticky = await repository.apply_probe_outcome(
            platform=platform,
            success=True,
            at=now + timedelta(seconds=4),
            policy=policy,
        )
        states["disabled_success_race"] = sticky.state.value

        half_open = await repository.administrative_enable(
            platform=platform,
            at=now + timedelta(seconds=5),
        )
        states["admin_enable"] = half_open.state.value
        half_open_failures = half_open.consecutive_failures

        recovered = await repository.apply_probe_outcome(
            platform=platform,
            success=True,
            at=now + timedelta(seconds=6),
            policy=policy,
        )
        states["half_open_success"] = recovered.state.value

        admin_disabled = await repository.administrative_disable(
            platform=platform,
            at=now + timedelta(seconds=7),
        )
        states["admin_disable"] = admin_disabled.state.value

        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "failure_4_stays_healthy": states["failure_4"] == "HEALTHY",
            "failure_5_degrades": states["failure_5"] == "DEGRADED",
            "failure_20_disables": states["failure_20"] == "DISABLED",
            "disabled_is_sticky": states["disabled_success_race"] == "DISABLED",
            "admin_enable_is_half_open": states["admin_enable"] == "DEGRADED",
            "admin_enable_resets_failures": half_open_failures == 0,
            "half_open_success_recovers": states["half_open_success"] == "HEALTHY",
            "admin_disable_disables": states["admin_disable"] == "DISABLED",
        }
    finally:
        if platform is not None:
            async with engine.begin() as connection:
                if original is None:
                    await connection.execute(
                        text("DELETE FROM platform_health WHERE platform=:platform"),
                        {"platform": platform},
                    )
                else:
                    await connection.execute(
                        text(
                            "UPDATE platform_health SET "
                            "state=:state,last_success_at=:last_success_at,last_failure_at=:last_failure_at,"
                            "success_rate_24h=:success_rate_24h,avg_latency_ms_24h=:avg_latency_ms_24h,"
                            "consecutive_failures=:consecutive_failures,error_count_24h=:error_count_24h,"
                            "success_count_24h=:success_count_24h,sustained_qps=:sustained_qps,"
                            "max_anchors=:max_anchors,updated_at=:updated_at WHERE platform=:platform"
                        ),
                        original,
                    )
            async with engine.connect() as connection:
                after = (
                    await connection.execute(
                        text("SELECT * FROM platform_health WHERE platform=:platform"),
                        {"platform": platform},
                    )
                ).mappings().one_or_none()
                restored = (after is None) if original is None else dict(after) == original
        await engine.dispose()

    checks["platform_health_restored"] = restored
    status = "PASS" if all(checks.values()) else "FAIL"
    payload = {
        "gate": "2.4",
        "probe": "postgresql_circuit_breaker_controlled",
        "status": status,
        "migration_head": head,
        "platform": platform,
        "thresholds": {
            "degraded": policy.degraded_failure_threshold,
            "disabled": policy.disabled_failure_threshold,
            "degraded_interval_multiplier": policy.degraded_interval_multiplier,
        },
        "states": states,
        "checks": checks,
        "provider_called": False,
        "notification_called": False,
        "database_write_performed": True,
        "cleanup_performed": True,
        "database_restored": restored,
        "live_truth_mutated": False,
        "gate0a_lifecycle_claimed": False,
        "worker_exactly_once_claimed": False,
        "provider_exactly_once_claimed": False,
        "production_approved": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
