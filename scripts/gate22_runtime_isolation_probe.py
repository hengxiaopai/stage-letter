#!/usr/bin/env python3
"""Gate 2.2 deterministic runtime-isolation acceptance probe.

Read-only with respect to PostgreSQL. No provider or notification network calls.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
    RetryAction,
    classify_retry,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)

EXPECTED_HEAD = "a63f4b2d9e71"


def provider_error(kind: ProviderFailureKind) -> ProviderOperationError:
    return ProviderOperationError(ProviderFailure(kind=kind, source="gate2.2.synthetic"))


async def main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            migration_head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()

    retry_matrix = {
        kind.value: classify_retry(provider_error(kind)).action.value
        for kind in ProviderFailureKind
    }

    transient_attempts = 0

    async def no_wait(_: float) -> None:
        return None

    transient_runtime = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=3,
            base_backoff_seconds=0,
        ),
        sleep=no_wait,
    )

    async def transient_operation() -> str:
        nonlocal transient_attempts
        transient_attempts += 1
        if transient_attempts == 1:
            raise provider_error(ProviderFailureKind.RATE_LIMITED)
        return "ok"

    transient_outcome = await transient_runtime.execute("douyin", transient_operation)

    auth_attempts = 0

    async def auth_operation() -> str:
        nonlocal auth_attempts
        auth_attempts += 1
        raise provider_error(ProviderFailureKind.AUTH_REQUIRED)

    auth_outcome = await transient_runtime.execute("bilibili", auth_operation)

    fake_now = 0.0
    starts: list[float] = []

    async def fake_sleep(delay: float) -> None:
        nonlocal fake_now
        fake_now += delay

    def fake_clock() -> float:
        return fake_now

    rate_runtime = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=2.0,
            max_attempts=1,
        ),
        sleep=fake_sleep,
        clock=fake_clock,
    )

    async def rate_operation() -> str:
        starts.append(fake_clock())
        return "ok"

    for _ in range(3):
        await rate_runtime.execute("huya", rate_operation)

    checks = {
        "migration_head_matches": migration_head == EXPECTED_HEAD,
        "timeout_retryable": classify_retry(TimeoutError()).action is RetryAction.RETRY,
        "rate_limited_retryable": retry_matrix[ProviderFailureKind.RATE_LIMITED.value] == "RETRY",
        "upstream_retryable": retry_matrix[ProviderFailureKind.UPSTREAM_ERROR.value] == "RETRY",
        "auth_not_blind_retry": retry_matrix[ProviderFailureKind.AUTH_REQUIRED.value] == "STOP",
        "ambiguous_not_blind_retry": retry_matrix[ProviderFailureKind.AMBIGUOUS.value] == "STOP",
        "transient_retry_succeeded": transient_outcome.succeeded and transient_attempts == 2,
        "auth_stopped_once": (not auth_outcome.succeeded) and auth_attempts == 1,
        "rate_starts_spaced": starts == [0.0, 0.5, 1.0],
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        json.dumps(
            {
                "gate": "2.2",
                "probe": "runtime_isolation_policy",
                "status": status,
                "migration_head": migration_head,
                "retry_matrix": retry_matrix,
                "transient_attempts": transient_attempts,
                "auth_attempts": auth_attempts,
                "rate_limit_starts": starts,
                "checks": checks,
                "provider_called": False,
                "notification_called": False,
                "database_write_performed": False,
                "live_truth_mutated": False,
                "gate0a_lifecycle_claimed": False,
                "worker_exactly_once_claimed": False,
                "provider_exactly_once_claimed": False,
                "production_approved": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
