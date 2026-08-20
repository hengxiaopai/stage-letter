#!/usr/bin/env python3
"""Gate 5.5 read-only PostgreSQL restart acceptance for the Admin surface."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routers.health import build_system_health
from api.services.admin_inquiry import list_deliveries, list_subscriptions, list_users
from api.services.admin_metrics import build_admin_metrics
from core.config import settings


EXPECTED_HEAD = "f52a9d1c4e81"


async def _snapshot(factory: async_sessionmaker) -> dict[str, int]:
    async with factory() as session:
        health = await build_system_health(session)
        # One AsyncSession owns one transactional connection at a time, so keep
        # the independent read projections sequential inside this session.
        users = await list_users(session)
        subscriptions = await list_subscriptions(session)
        deliveries = await list_deliveries(session)
        metrics = await build_admin_metrics(session)
    return {
        "platform_count": len(health["platforms"]),
        "user_page_count": len(users.items),
        "subscription_page_count": len(subscriptions.items),
        "delivery_page_count": len(deliveries.items),
        "platform_metric_rows": len(metrics["platform_health_24h"]),
        "delivery_metric_rows": len(metrics["deliveries_by_channel_state"]),
        "error_metric_rows": len(metrics["delivery_errors_by_code"]),
    }


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if head != EXPECTED_HEAD:
            print(json.dumps({"gate": "5.5", "status": "BLOCKED", "migration_head": head, "expected_head": EXPECTED_HEAD}, indent=2))
            return 2

        before = await _snapshot(async_sessionmaker(engine, expire_on_commit=False))
        await engine.dispose()

        restarted_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            after = await _snapshot(async_sessionmaker(restarted_engine, expire_on_commit=False))
        finally:
            await restarted_engine.dispose()

        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "initial_admin_reads_succeeded": all(value >= 0 for value in before.values()),
            "restart_admin_reads_succeeded": all(value >= 0 for value in after.values()),
            "platform_projection_persisted": before["platform_count"] == after["platform_count"],
            "metric_platform_projection_persisted": before["platform_metric_rows"] == after["platform_metric_rows"],
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        print(
            json.dumps(
                {
                    "gate": "5.5",
                    "probe": "postgresql_admin_restart_read_only",
                    "status": status,
                    "migration_head": head,
                    "before_restart": before,
                    "after_restart": after,
                    "checks": checks,
                    "provider_called": False,
                    "notification_called": False,
                    "database_write_performed": False,
                    "live_truth_mutated": False,
                    "gate0a_lifecycle_claimed": False,
                    "production_approved": False,
                },
                indent=2,
            )
        )
        return 0 if status == "PASS" else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
