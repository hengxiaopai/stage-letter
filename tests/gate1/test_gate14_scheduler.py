from __future__ import annotations

import ast
import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.services.monitoring_probe import MonitoringProbeResult
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from workers.monitoring.scheduler import (
    MonitoringScheduler,
    MonitoringSchedulerPolicy,
    make_probe_id,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_PATH = ROOT / "workers" / "monitoring" / "scheduler.py"


def _account(account_id: str, platform: str = "douyin") -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform=platform,
        platform_user_id=f"provider-{account_id}",
        enabled=True,
    )


def _result(request, status: LiveStatus = LiveStatus.OFFLINE) -> MonitoringProbeResult:
    return MonitoringProbeResult(
        observation=LiveObservation(
            observation_id=request.probe_id,
            account_id=request.account_id,
            status=status,
            observed_at=datetime.now(timezone.utc),
            source="test.provider",
        ),
        reused_existing=False,
    )


class _Targets:
    def __init__(self, pages: dict[str | None, tuple[PlatformAccount, ...]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str | None, int]] = []

    async def list_targets(self, *, after_account_id=None, limit=100):
        self.calls.append((after_account_id, limit))
        return self.pages.get(after_account_id, ())


class _Probe:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return await self.handler(request)


class Gate14SchedulerContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_validation_and_capped_backoff(self) -> None:
        policy = MonitoringSchedulerPolicy(
            max_concurrency=4,
            per_platform_concurrency=2,
            max_attempts=4,
            base_backoff_seconds=1.0,
            max_backoff_seconds=2.5,
        )
        self.assertEqual(1.0, policy.backoff_seconds(1))
        self.assertEqual(2.0, policy.backoff_seconds(2))
        self.assertEqual(2.5, policy.backoff_seconds(3))
        with self.assertRaises(ValueError):
            MonitoringSchedulerPolicy(cadence_seconds=0)
        with self.assertRaises(ValueError):
            MonitoringSchedulerPolicy(max_concurrency=1, per_platform_concurrency=2)
        with self.assertRaises(ValueError):
            MonitoringSchedulerPolicy(page_size=1001)

    async def test_probe_id_is_stable_distinct_and_bounded(self) -> None:
        first = make_probe_id("cycle-1", "42")
        self.assertEqual(first, make_probe_id("cycle-1", "42"))
        self.assertNotEqual(first, make_probe_id("cycle-2", "42"))
        self.assertNotEqual(first, make_probe_id("cycle-1", "43"))
        self.assertLessEqual(len(first), 255)
        with self.assertRaises(ValueError):
            make_probe_id("", "42")

    async def test_same_logical_probe_is_single_flight_inside_scheduler_process(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            started.set()
            await release.wait()
            return _result(request)

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(_Targets({}), probe)  # type: ignore[arg-type]
        account = _account("1")
        first = asyncio.create_task(scheduler.run_target(cycle_id="c1", account=account))
        await started.wait()
        second = asyncio.create_task(scheduler.run_target(cycle_id="c1", account=account))
        await asyncio.sleep(0)
        self.assertEqual(1, len(probe.calls))
        release.set()
        first_outcome, second_outcome = await asyncio.gather(first, second)
        self.assertTrue(first_outcome.succeeded)
        self.assertTrue(second_outcome.succeeded)
        self.assertEqual(first_outcome.request, second_outcome.request)
        self.assertEqual(1, len(probe.calls))

    async def test_retry_reuses_exact_request_and_exponential_backoff(self) -> None:
        attempts = 0
        delays: list[float] = []

        async def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("transient")
            return _result(request)

        async def sleep(delay: float) -> None:
            delays.append(delay)

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(
            _Targets({}),
            probe,  # type: ignore[arg-type]
            policy=MonitoringSchedulerPolicy(
                max_concurrency=2,
                per_platform_concurrency=1,
                max_attempts=3,
                base_backoff_seconds=1,
                max_backoff_seconds=8,
            ),
            sleep=sleep,
        )
        outcome = await scheduler.run_target(cycle_id="retry", account=_account("2"))
        self.assertTrue(outcome.succeeded)
        self.assertEqual(3, outcome.attempts)
        self.assertEqual([1, 2], delays)
        self.assertEqual(1, len({call.probe_id for call in probe.calls}))
        self.assertEqual(1, len({call.account_id for call in probe.calls}))

    async def test_retry_exhaustion_returns_error_without_fabricated_observation(self) -> None:
        async def handler(request):
            raise ConnectionError("still down")

        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(
            _Targets({}),
            probe,  # type: ignore[arg-type]
            policy=MonitoringSchedulerPolicy(
                max_concurrency=1,
                per_platform_concurrency=1,
                max_attempts=2,
            ),
            sleep=sleep,
        )
        outcome = await scheduler.run_target(cycle_id="fail", account=_account("3"))
        self.assertFalse(outcome.succeeded)
        self.assertIsNone(outcome.result)
        self.assertIsInstance(outcome.error, ConnectionError)
        self.assertEqual(2, outcome.attempts)
        self.assertEqual(2, len(probe.calls))
        self.assertEqual([1.0], delays)

    async def test_non_retryable_application_failure_is_not_retried(self) -> None:
        async def handler(request):
            raise ApplicationInvariantError("identity changed")

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(_Targets({}), probe)  # type: ignore[arg-type]
        outcome = await scheduler.run_target(cycle_id="bad", account=_account("4"))
        self.assertFalse(outcome.succeeded)
        self.assertIsInstance(outcome.error, ApplicationInvariantError)
        self.assertEqual(1, outcome.attempts)
        self.assertEqual(1, len(probe.calls))

    async def test_successful_unknown_observation_is_not_retried(self) -> None:
        async def handler(request):
            return _result(request, LiveStatus.UNKNOWN)

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(_Targets({}), probe)  # type: ignore[arg-type]
        outcome = await scheduler.run_target(cycle_id="unknown", account=_account("5"))
        self.assertTrue(outcome.succeeded)
        self.assertIs(LiveStatus.UNKNOWN, outcome.result.observation.status)  # type: ignore[union-attr]
        self.assertEqual(1, outcome.attempts)
        self.assertEqual(1, len(probe.calls))

    async def test_global_and_per_platform_concurrency_are_bounded(self) -> None:
        active_total = 0
        max_total = 0
        active_by_platform: dict[str, int] = {}
        max_by_platform: dict[str, int] = {}
        release = asyncio.Event()
        two_started = asyncio.Event()
        platform_by_account = {"10": "douyin", "11": "douyin", "12": "bilibili"}

        async def handler(request):
            nonlocal active_total, max_total
            platform = platform_by_account[request.account_id]
            active_total += 1
            active_by_platform[platform] = active_by_platform.get(platform, 0) + 1
            max_total = max(max_total, active_total)
            max_by_platform[platform] = max(
                max_by_platform.get(platform, 0), active_by_platform[platform]
            )
            if active_total == 2:
                two_started.set()
            try:
                await release.wait()
                return _result(request)
            finally:
                active_total -= 1
                active_by_platform[platform] -= 1

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(
            _Targets({}),
            probe,  # type: ignore[arg-type]
            policy=MonitoringSchedulerPolicy(
                max_concurrency=2,
                per_platform_concurrency=1,
            ),
        )
        tasks = [
            asyncio.create_task(
                scheduler.run_target(
                    cycle_id="bounds",
                    account=_account(account_id, platform),
                )
            )
            for account_id, platform in platform_by_account.items()
        ]
        await two_started.wait()
        self.assertEqual(2, max_total)
        self.assertLessEqual(max_by_platform.get("douyin", 0), 1)
        self.assertLessEqual(max_by_platform.get("bilibili", 0), 1)
        release.set()
        outcomes = await asyncio.gather(*tasks)
        self.assertTrue(all(item.succeeded for item in outcomes))
        self.assertLessEqual(max_total, 2)
        self.assertLessEqual(max_by_platform.get("douyin", 0), 1)

    async def test_run_cycle_pages_targets_and_probes_each_account_once(self) -> None:
        pages = {
            None: (_account("1"), _account("2", "bilibili")),
            "2": (_account("3", "huya"), _account("4", "douyu")),
            "4": (),
        }
        targets = _Targets(pages)

        async def handler(request):
            return _result(request)

        probe = _Probe(handler)
        scheduler = MonitoringScheduler(
            targets,  # type: ignore[arg-type]
            probe,  # type: ignore[arg-type]
            policy=MonitoringSchedulerPolicy(
                max_concurrency=4,
                per_platform_concurrency=2,
                page_size=2,
            ),
        )
        outcomes = await scheduler.run_cycle("cycle-pages")
        self.assertEqual(4, len(outcomes))
        self.assertEqual([(None, 2), ("2", 2), ("4", 2)], targets.calls)
        self.assertEqual({"1", "2", "3", "4"}, {call.account_id for call in probe.calls})
        self.assertEqual(4, len({call.probe_id for call in probe.calls}))

    async def test_scheduler_owns_mechanics_not_live_truth_or_legacy_runtime(self) -> None:
        source = SCHEDULER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SCHEDULER_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "platform_adapters",
            "experiments",
            "core",
            "api",
            "requests",
            "httpx",
            "streamget",
        )
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("Notification", source)
        self.assertNotIn("room_id", source)
        self.assertNotIn("title", source)
        self.assertNotIn("LiveStatus.OFFLINE", source)


if __name__ == "__main__":
    unittest.main()
