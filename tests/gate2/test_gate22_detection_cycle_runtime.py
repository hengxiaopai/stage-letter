from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stage_letter.application.services.monitoring_probe import MonitoringProbeResult
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
)
from workers.detection_runtime import DetectionCycleRuntime


def _account(account_id: str, platform: str) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform=platform,
        platform_user_id=f"provider-{account_id}",
        enabled=True,
    )


class _Targets:
    MAX_PAGE_SIZE = 1000

    def __init__(self, accounts: tuple[PlatformAccount, ...]) -> None:
        self.accounts = accounts
        self.calls: list[tuple[str | None, int]] = []

    async def list_targets(self, *, after_account_id=None, limit=100):
        self.calls.append((after_account_id, limit))
        if after_account_id is not None:
            return ()
        return self.accounts[:limit]


class _Probe:
    def __init__(self) -> None:
        self.calls = []
        self.fail_once = True

    async def execute(self, request):
        self.calls.append(request)
        if request.account_id == "1" and self.fail_once:
            self.fail_once = False
            raise TimeoutError("synthetic transient")
        return MonitoringProbeResult(
            observation=LiveObservation(
                observation_id=request.probe_id,
                account_id=request.account_id,
                status=LiveStatus.UNKNOWN,
                observed_at=datetime.now(timezone.utc),
                source="gate2.2.synthetic",
            ),
            reused_existing=False,
        )


@pytest.mark.asyncio
async def test_detection_cycle_uses_due_targets_and_stable_probe_id_across_retry() -> None:
    targets = _Targets((_account("1", "douyin"), _account("2", "bilibili")))
    probe = _Probe()

    async def no_wait(_: float) -> None:
        return None

    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=2,
            base_backoff_seconds=0,
        ),
        sleep=no_wait,
    )
    runtime = DetectionCycleRuntime(targets, probe, coordinator)  # type: ignore[arg-type]
    result = await runtime.run_cycle("gate22-cycle")

    assert result.succeeded
    assert len(result.outcomes) == 2
    account_one_calls = [item for item in probe.calls if item.account_id == "1"]
    assert len(account_one_calls) == 2
    assert len({item.probe_id for item in account_one_calls}) == 1
    assert account_one_calls[0].probe_id.startswith("monitor:")
    assert targets.calls == [(None, 100)]


@pytest.mark.asyncio
async def test_detection_cycle_does_not_interpret_unknown_as_failure() -> None:
    targets = _Targets((_account("3", "huya"),))
    probe = _Probe()
    probe.fail_once = False
    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=1,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=1,
        )
    )
    runtime = DetectionCycleRuntime(targets, probe, coordinator)  # type: ignore[arg-type]
    result = await runtime.run_cycle("unknown-is-data")

    assert result.succeeded
    assert len(result.outcomes) == 1
    observation = result.outcomes[0].value.observation  # type: ignore[union-attr]
    assert observation.status is LiveStatus.UNKNOWN
