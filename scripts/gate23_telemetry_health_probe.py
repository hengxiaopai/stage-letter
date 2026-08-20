#!/usr/bin/env python3
"""Gate 2.3 controlled PostgreSQL telemetry/health acceptance.

Writes one synthetic operational telemetry row through the formal Gate 2.3
repository, verifies the persisted probe/health evidence, then removes that row
and restores the exact pre-probe platform_health snapshot. It never calls a
provider and never mutates canonical LiveObservation/Session/Event truth.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.detection.telemetry import ProbeTelemetryRecord
from stage_letter.infrastructure.detection.telemetry import SQLAlchemyDetectionTelemetryRepository

EXPECTED_HEAD = "a63f4b2d9e71"

HEALTH_SELECT = """
SELECT platform, state, last_success_at, last_failure_at, success_rate_24h,
       avg_latency_ms_24h, consecutive_failures, error_count_24h,
       success_count_24h, sustained_qps, max_anchors, updated_at
FROM platform_health WHERE platform=:platform
"""


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    probe_run_id: int | None = None
    platform: str | None = None
    prior_health: dict | None = None
    cleanup_performed = False
    database_restored = False
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            account = (
                await connection.execute(
                    text(
                        "SELECT id, platform FROM platform_accounts "
                        "WHERE is_disabled=false ORDER BY id ASC LIMIT 1"
                    )
                )
            ).mappings().one_or_none()
        if account is None:
            payload = {
                "gate": "2.3",
                "probe": "postgresql_telemetry_health_controlled",
                "status": "BLOCKED",
                "reason": "no enabled platform account exists for controlled telemetry",
                "migration_head": head,
                "provider_called": False,
                "notification_called": False,
                "database_write_performed": False,
                "live_truth_mutated": False,
                "production_approved": False,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return 2

        account_id = str(account["id"])
        platform = str(account["platform"])
        async with engine.connect() as connection:
            prior = (
                await connection.execute(text(HEALTH_SELECT), {"platform": platform})
            ).mappings().one_or_none()
            prior_health = None if prior is None else dict(prior)

        now = datetime.now(timezone.utc)
        record = ProbeTelemetryRecord(
            probe_id=f"monitor:gate23-acceptance:{uuid4().hex}",
            account_id=account_id,
            platform=platform,
            started_at=now,
            finished_at=now + timedelta(milliseconds=125),
            success=True,
            attempts=1,
            latency_ms=125,
            observation_status="UNKNOWN",
        )
        service = DetectionTelemetryApplicationService(
            SQLAlchemyDetectionTelemetryRepository(session_factory)
        )
        persisted = await service.record(record)
        probe_run_id = persisted.probe_run_id

        async with engine.connect() as connection:
            probe_row = (
                await connection.execute(
                    text(
                        "SELECT success, error_message, snapshot FROM probe_runs "
                        "WHERE id=:probe_run_id"
                    ),
                    {"probe_run_id": probe_run_id},
                )
            ).mappings().one_or_none()
            health_after = (
                await connection.execute(text(HEALTH_SELECT), {"platform": platform})
            ).mappings().one_or_none()

        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "probe_run_persisted": probe_row is not None,
            "probe_marked_success": probe_row is not None and probe_row["success"] is True,
            "telemetry_schema_tagged": (
                probe_row is not None
                and (probe_row["snapshot"] or {}).get("telemetry_schema") == "gate2.3"
            ),
            "probe_id_persisted": (
                probe_row is not None
                and (probe_row["snapshot"] or {}).get("probe_id") == record.probe_id
            ),
            "health_row_persisted": health_after is not None,
            "health_success_count_present": persisted.health.success_count_24h >= 1,
            "health_consecutive_failures_zero": persisted.health.consecutive_failures == 0,
            "health_last_success_persisted": persisted.health.last_success_at is not None,
            "health_state_not_transitioned_by_gate23": (
                prior_health is None
                or persisted.health.state.value == str(prior_health["state"])
            ),
        }

        # Cleanup/restore is explicit acceptance hygiene. It operates only on the
        # synthetic probe row and the operational platform_health row.
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM probe_runs WHERE id=:probe_run_id"),
                {"probe_run_id": probe_run_id},
            )
            if prior_health is None:
                await connection.execute(
                    text("DELETE FROM platform_health WHERE platform=:platform"),
                    {"platform": platform},
                )
            else:
                await connection.execute(
                    text(
                        "UPDATE platform_health SET state=:state, "
                        "last_success_at=:last_success_at, last_failure_at=:last_failure_at, "
                        "success_rate_24h=:success_rate_24h, "
                        "avg_latency_ms_24h=:avg_latency_ms_24h, "
                        "consecutive_failures=:consecutive_failures, "
                        "error_count_24h=:error_count_24h, "
                        "success_count_24h=:success_count_24h, "
                        "sustained_qps=:sustained_qps, max_anchors=:max_anchors, "
                        "updated_at=:updated_at WHERE platform=:platform"
                    ),
                    prior_health,
                )
        cleanup_performed = True

        async with engine.connect() as connection:
            remaining_probe = await connection.scalar(
                text("SELECT count(*) FROM probe_runs WHERE id=:probe_run_id"),
                {"probe_run_id": probe_run_id},
            )
            restored = (
                await connection.execute(text(HEALTH_SELECT), {"platform": platform})
            ).mappings().one_or_none()
        restored_health = None if restored is None else dict(restored)
        database_restored = int(remaining_probe or 0) == 0 and restored_health == prior_health
        checks["synthetic_probe_cleaned"] = int(remaining_probe or 0) == 0
        checks["platform_health_restored"] = restored_health == prior_health

        status = "PASS" if all(checks.values()) and database_restored else "BLOCKED"
        payload = {
            "gate": "2.3",
            "probe": "postgresql_telemetry_health_controlled",
            "status": status,
            "migration_head": head,
            "account_id": account_id,
            "platform": platform,
            "probe_run_id": probe_run_id,
            "health_state_after_record": persisted.health.state.value,
            "success_count_24h_after_record": persisted.health.success_count_24h,
            "error_count_24h_after_record": persisted.health.error_count_24h,
            "consecutive_failures_after_record": persisted.health.consecutive_failures,
            "checks": checks,
            "provider_called": False,
            "notification_called": False,
            "database_write_performed": True,
            "cleanup_performed": cleanup_performed,
            "database_restored": database_restored,
            "live_truth_mutated": False,
            "platform_health_state_transition_applied": False,
            "gate0a_lifecycle_claimed": False,
            "worker_exactly_once_claimed": False,
            "provider_exactly_once_claimed": False,
            "production_approved": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if status == "PASS" else 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
