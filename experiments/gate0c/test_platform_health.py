#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from platform_health import (
    CanonicalStatus,
    FailureKind,
    HealthConfig,
    HealthState,
    HealthTracker,
    ProbeSample,
    aggregate_health,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 17, 15, 40, tzinfo=TZ)


def sample(
    number: int,
    status: CanonicalStatus,
    *,
    latency_ms: int = 300,
    failure_kind: FailureKind | None = None,
    started_at: datetime | None = None,
    sample_id: str | None = None,
) -> ProbeSample:
    started = started_at or (BASE + timedelta(seconds=number))
    return ProbeSample(
        sample_id=sample_id or f"sample-{number}",
        started_at=started,
        completed_at=started + timedelta(milliseconds=latency_ms),
        status=status,
        latency_ms=latency_ms,
        failure_kind=failure_kind,
        source="gate0c-test",
    )


class PlatformHealthGate0CTests(unittest.TestCase):
    def test_01_first_clean_decisive_probe_establishes_healthy(self) -> None:
        tracker = HealthTracker()
        result = tracker.process(sample(1, CanonicalStatus.OFFLINE))
        self.assertEqual(result.current_state, HealthState.HEALTHY)
        self.assertEqual(result.canonical_status, CanonicalStatus.OFFLINE)

    def test_02_one_transient_unknown_does_not_immediately_degrade_healthy(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.LIVE))
        result = tracker.process(sample(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT))
        self.assertEqual(result.current_state, HealthState.HEALTHY)
        self.assertEqual(tracker.consecutive_failures, 1)
        self.assertEqual(result.canonical_status, CanonicalStatus.UNKNOWN)

    def test_03_two_consecutive_failures_degrade(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.OFFLINE))
        tracker.process(sample(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK))
        result = tracker.process(sample(3, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT))
        self.assertEqual(result.current_state, HealthState.DEGRADED)

    def test_04_four_consecutive_failures_become_unavailable(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.LIVE))
        for number in range(2, 6):
            result = tracker.process(sample(number, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK))
        self.assertEqual(result.current_state, HealthState.UNAVAILABLE)
        self.assertEqual(tracker.consecutive_failures, 4)

    def test_05_hard_auth_or_blocked_failure_is_immediately_unavailable(self) -> None:
        for kind in (FailureKind.AUTH, FailureKind.BLOCKED):
            with self.subTest(kind=kind):
                tracker = HealthTracker()
                tracker.process(sample(1, CanonicalStatus.OFFLINE))
                result = tracker.process(sample(2, CanonicalStatus.UNKNOWN, failure_kind=kind))
                self.assertEqual(result.current_state, HealthState.UNAVAILABLE)

    def test_06_unavailable_requires_two_clean_successes_to_recover_healthy(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.LIVE))
        for number in range(2, 6):
            tracker.process(sample(number, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT))
        first = tracker.process(sample(6, CanonicalStatus.LIVE))
        second = tracker.process(sample(7, CanonicalStatus.LIVE))
        self.assertEqual(first.current_state, HealthState.DEGRADED)
        self.assertEqual(second.current_state, HealthState.HEALTHY)

    def test_07_slow_decisive_probe_degrades_health_but_preserves_status(self) -> None:
        tracker = HealthTracker(HealthConfig(slow_latency_ms=1000))
        tracker.process(sample(1, CanonicalStatus.OFFLINE, latency_ms=100))
        result = tracker.process(sample(2, CanonicalStatus.LIVE, latency_ms=1200))
        self.assertEqual(result.current_state, HealthState.DEGRADED)
        self.assertEqual(result.canonical_status, CanonicalStatus.LIVE)
        self.assertEqual(tracker.slow_samples, 1)

    def test_08_unknown_without_error_code_is_health_failure_not_offline(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.OFFLINE))
        result = tracker.process(sample(2, CanonicalStatus.UNKNOWN))
        self.assertEqual(result.canonical_status, CanonicalStatus.UNKNOWN)
        self.assertEqual(tracker.last_failure_kind, FailureKind.EMPTY)
        self.assertEqual(tracker.consecutive_failures, 1)

    def test_09_stale_delayed_failure_cannot_regress_newer_healthy_result(self) -> None:
        tracker = HealthTracker()
        newer_started = BASE + timedelta(seconds=20)
        newer = sample(20, CanonicalStatus.LIVE, started_at=newer_started)
        old = sample(10, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT, started_at=BASE + timedelta(seconds=10))
        tracker.process(newer)
        result = tracker.process(old)
        self.assertTrue(result.stale)
        self.assertFalse(result.accepted)
        self.assertEqual(tracker.state, HealthState.HEALTHY)
        self.assertEqual(tracker.consecutive_failures, 0)

    def test_10_duplicate_precedes_stale_classification(self) -> None:
        tracker = HealthTracker()
        first = sample(1, CanonicalStatus.OFFLINE)
        tracker.process(first)
        tracker.process(sample(2, CanonicalStatus.LIVE))
        replay = tracker.process(first)
        self.assertTrue(replay.duplicate)
        self.assertFalse(replay.stale)

    def test_11_newer_unknown_watermark_blocks_older_failure_from_double_counting(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.LIVE))
        tracker.process(sample(5, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT))
        before = tracker.snapshot()
        result = tracker.process(sample(4, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK, started_at=BASE + timedelta(seconds=4)))
        self.assertTrue(result.stale)
        self.assertEqual(tracker.consecutive_failures, before.consecutive_failures)
        self.assertEqual(tracker.state, before.state)

    def test_12_snapshot_restore_preserves_recovery_streak_watermark_and_idempotency(self) -> None:
        tracker = HealthTracker()
        tracker.process(sample(1, CanonicalStatus.OFFLINE))
        for number in range(2, 6):
            tracker.process(sample(number, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK))
        first_recovery = sample(6, CanonicalStatus.OFFLINE)
        tracker.process(first_recovery)
        snapshot = tracker.snapshot()

        restarted = HealthTracker.from_snapshot(snapshot)
        self.assertEqual(restarted.state, HealthState.DEGRADED)
        self.assertEqual(restarted.consecutive_clean_successes, 1)
        duplicate = restarted.process(first_recovery)
        self.assertTrue(duplicate.duplicate)
        recovered = restarted.process(sample(7, CanonicalStatus.OFFLINE))
        self.assertEqual(recovered.current_state, HealthState.HEALTHY)

    def test_13_partial_platform_failure_aggregates_to_degraded(self) -> None:
        self.assertEqual(aggregate_health([HealthState.HEALTHY, HealthState.UNAVAILABLE]), HealthState.DEGRADED)
        self.assertEqual(aggregate_health([HealthState.HEALTHY, HealthState.DEGRADED]), HealthState.DEGRADED)

    def test_14_all_unavailable_aggregates_to_unavailable(self) -> None:
        self.assertEqual(aggregate_health([HealthState.UNAVAILABLE, HealthState.UNAVAILABLE]), HealthState.UNAVAILABLE)

    def test_15_all_healthy_aggregates_to_healthy(self) -> None:
        self.assertEqual(aggregate_health([HealthState.HEALTHY, HealthState.HEALTHY]), HealthState.HEALTHY)

    def test_16_equal_start_timestamp_is_not_falsely_stale(self) -> None:
        tracker = HealthTracker()
        same = BASE + timedelta(seconds=1)
        tracker.process(sample(1, CanonicalStatus.OFFLINE, started_at=same, sample_id="a"))
        result = tracker.process(sample(2, CanonicalStatus.LIVE, started_at=same, sample_id="b"))
        self.assertFalse(result.stale)
        self.assertTrue(result.accepted)
        self.assertEqual(result.canonical_status, CanonicalStatus.LIVE)

    def test_17_failed_probe_cannot_claim_decisive_live_or_offline(self) -> None:
        with self.assertRaises(ValueError):
            sample(1, CanonicalStatus.OFFLINE, failure_kind=FailureKind.TIMEOUT)

    def test_18_slow_success_recovers_unavailable_only_to_degraded(self) -> None:
        tracker = HealthTracker(HealthConfig(slow_latency_ms=1000))
        tracker.process(sample(1, CanonicalStatus.LIVE))
        tracker.process(sample(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.BLOCKED))
        self.assertEqual(tracker.state, HealthState.UNAVAILABLE)
        result = tracker.process(sample(3, CanonicalStatus.LIVE, latency_ms=1500))
        self.assertEqual(result.current_state, HealthState.DEGRADED)
        self.assertEqual(result.canonical_status, CanonicalStatus.LIVE)

    def test_19_config_validation_rejects_invalid_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            HealthConfig(degrade_after_failures=0)
        with self.assertRaises(ValueError):
            HealthConfig(degrade_after_failures=3, unavailable_after_failures=2)
        with self.assertRaises(ValueError):
            HealthConfig(recover_after_clean_successes=0)


if __name__ == "__main__":
    unittest.main()
