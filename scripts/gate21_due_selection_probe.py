#!/usr/bin/env python3
"""Gate 2.1 read-only PostgreSQL due-selection acceptance probe."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.detection.due import DetectionCadencePolicy, is_due, normalize_polling_tier
from stage_letter.infrastructure.detection import SQLAlchemyDetectionScheduleRepository

EXPECTED_HEAD = "a63f4b2d9e71"


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    policy = DetectionCadencePolicy()
    now = datetime.now(timezone.utc)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        repository = SQLAlchemyDetectionScheduleRepository(session_factory)
        rows = []
        cursor = None
        while True:
            page = await repository.list_schedule_rows(after_account_id=cursor, limit=1000)
            if not page:
                break
            rows.extend(page)
            cursor = page[-1].account.account_id
            if len(page) < 1000:
                break

        tier_counts: Counter[str] = Counter()
        due_counts: Counter[str] = Counter()
        never_probed = 0
        corrupt_tier_fallbacks = 0
        for row in rows:
            tier = normalize_polling_tier(row.polling_tier_raw)
            tier_counts[tier.value] += 1
            raw = (row.polling_tier_raw or "").strip().lower()
            if raw and raw not in {"hot", "warm", "cold"}:
                corrupt_tier_fallbacks += 1
            if row.last_probe_at is None:
                never_probed += 1
            if is_due(now=now, tier=tier, last_probe_at=row.last_probe_at, policy=policy):
                due_counts[tier.value] += 1

        checks = {
            "migration_head_matches": head == EXPECTED_HEAD,
            "cadence_hot_30": int(policy.interval(normalize_polling_tier("hot")).total_seconds()) == 30,
            "cadence_warm_60": int(policy.interval(normalize_polling_tier("warm")).total_seconds()) == 60,
            "cadence_cold_300": int(policy.interval(normalize_polling_tier("cold")).total_seconds()) == 300,
        }
        status = "PASS" if all(checks.values()) else "BLOCKED"
        payload = {
            "gate": "2.1",
            "probe": "postgresql_due_selection_read_only",
            "status": status,
            "migration_head": head,
            "enabled_accounts_examined": len(rows),
            "tier_counts": dict(tier_counts),
            "due_counts": dict(due_counts),
            "never_probed_count": never_probed,
            "corrupt_tier_fallbacks": corrupt_tier_fallbacks,
            "cadence_seconds": {"hot": 30, "warm": 60, "cold": 300},
            "checks": checks,
            "provider_called": False,
            "notification_called": False,
            "database_write_performed": False,
            "gate0a_lifecycle_claimed": False,
            "worker_exactly_once_claimed": False,
            "provider_exactly_once_claimed": False,
            "production_approved": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if status == "PASS" else 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
