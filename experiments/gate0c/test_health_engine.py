#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from health_engine import (
    FailureClass,
    HealthEngine,
    HealthPolicy,
    HealthSample,
    HealthState,
    ProbeOutcome,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 17, 15, 40, tzinfo=TZ)


def success(number: int, latency_ms: int = 300) -> HealthSample:
    return HealthSample(
        sample_id=f"sample-{number}",
        outcome=ProbeOutcome.SUCCESS,
        completed_at=BASE + timedelta(seconds=number),
        latency_ms=latency_ms,
    )


def failure(
    number: int,
    failure_class: FailureClass = FailureClass.TIMEOUT,
    error_type: str = "TEST_FAILURE",
) -> HealthSample:
    return HealthSample(
        sample_id=f"sample-{number}",
        outcome=ProbeOutcome.FAILURE,
        completed_at=BASE + timedelta(seconds=number),
        latency_ms=5000,
        failure_class=failure_class,
        error_type=error_type,
    )


class HealthEngineGate0CTests(unittest.TestCase):
    def test_01_new_route_starts_unproven(self) -> None:
        engine = HealthEngine()
        self.assertEqual(engine.state, HealthState.UNPROVEN)
        self.assertEqual(engine.snapshot().total_samples, 0)

    def test_02_first_success_proves_healthy(self) -> None:
        engine = HealthEngine()
        result = engine.process(success(1))
        self.assertTrue(result.accepted)
        self.assertEqual(result.current_state, HealthState.HEALTHY)
        self.assertTrue(result.state_changed)

    def test_03_single_failure_does_not_overreact(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        result = engine.process(failure(2))
        self.assertEqual(result.current_state, HealthState.HEALTHY)
        self.assertEqual(engine.snapshot().consecutive_failures, 1)

    def test_04_two_consecutive_failures_degrade(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        engine.process(failure(2))
        result = engine.process(failure(3))
        self.assertEqual(result.current_state, HealthState.DEGRADED)
        self.assertEqual(engine.snapshot().consecutive_failures, 2)

    def test_05_five_consecutive_failures_become_unavailable(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        for number in range(2, 7):
            result = engine.process(failure(number))
        self.assertEqual(result.current_state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.snapshot().consecutive_failures, 5)

    def test_06_degraded_route_requires_two_successes_to_recover(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        engine.process(failure(2))
        engine.process(failure(3))
        first = engine.process(success(4))
        self.assertEqual(first.current_state, HealthState.DEGRADED)
        second = engine.process(success(5))
        self.assertEqual(second.current_state, HealthState.HEALTHY)

    def test_07_unavailable_route_requires_two_successes_to_recover(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        for number in range(2, 7):
            engine.process(failure(number))
        self.assertEqual(engine.state, HealthState.UNAVAILABLE)
        first = engine.process(success(7))
        self.assertEqual(first.current_state, HealthState.UNAVAILABLE)
        second = engine.process(success(8))
        self.assertEqual(second.current_state, HealthState.HEALTHY)

    def test_08_failed_recovery_does_not_improve_unavailable_state(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        for number in range(2, 7):
            engine.process(failure(number))
        engine.process(success(7))
        result = engine.process(failure(8))
        self.assertEqual(result.current_state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.snapshot().consecutive_failures, 1)

    def test_09_duplicate_sample_is_idempotent(self) -> None:
        engine = HealthEngine()
        probe = failure(1)
        first = engine.process(probe)
        duplicate = engine.process(probe)
        snapshot = engine.snapshot()
        self.assertTrue(first.accepted)
        self.assertFalse(duplicate.accepted)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(snapshot.total_samples, 1)
        self.assertEqual(snapshot.failure_count, 1)
        self.assertEqual(snapshot.consecutive_failures, 1)

    def test_10_failure_reason_is_normalized_and_retained(self) -> None:
        engine = HealthEngine()
        engine.process(
            failure(
                1,
                failure_class=FailureClass.RATE_LIMIT,
                error_type="HTTP_429",
            )
        )
        snapshot = engine.snapshot()
        self.assertEqual(snapshot.last_failure_class, FailureClass.RATE_LIMIT)
        self.assertEqual(snapshot.last_error_type, "HTTP_429")
        self.assertEqual(snapshot.last_failure_at, BASE + timedelta(seconds=1))

    def test_11_success_does_not_erase_last_failure_diagnostic(self) -> None:
        engine = HealthEngine()
        engine.process(failure(1, FailureClass.PARSE_SCHEMA, "SCHEMA_DRIFT"))
        engine.process(success(2))
        snapshot = engine.snapshot()
        self.assertEqual(snapshot.last_failure_class, FailureClass.PARSE_SCHEMA)
        self.assertEqual(snapshot.last_error_type, "SCHEMA_DRIFT")
        self.assertEqual(snapshot.last_success_at, BASE + timedelta(seconds=2))

    def test_12_snapshot_restore_preserves_health_and_idempotency(self) -> None:
        engine = HealthEngine()
        engine.process(success(1))
        engine.process(failure(2))
        engine.process(failure(3, FailureClass.TRANSPORT, "CONNECT_ERROR"))
        restored = HealthEngine.from_snapshot(engine.snapshot())
        self.assertEqual(restored.state, HealthState.DEGRADED)
        self.assertEqual(restored.snapshot(), engine.snapshot())
        duplicate = restored.process(failure(3, FailureClass.TRANSPORT, "CONNECT_ERROR"))
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(restored.snapshot().total_samples, 3)

    def test_13_unproven_route_can_degrade_then_become_unavailable(self) -> None:
        engine = HealthEngine()
        for number in range(1, 6):
            engine.process(failure(number))
        self.assertEqual(engine.state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.snapshot().success_count, 0)

    def test_14_failure_classes_do_not_change_live_state_semantics_here(self) -> None:
        for failure_class in FailureClass:
            engine = HealthEngine()
            engine.process(success(1))
            engine.process(failure(2, failure_class, failure_class.value))
            result = engine.process(failure(3, failure_class, failure_class.value))
            self.assertEqual(result.current_state, HealthState.DEGRADED)

    def test_15_policy_is_configurable_and_validated(self) -> None:
        policy = HealthPolicy(
            degraded_after_failures=1,
            unavailable_after_failures=3,
            recover_after_successes=3,
        )
        engine = HealthEngine(policy)
        self.assertEqual(engine.process(failure(1)).current_state, HealthState.DEGRADED)
        engine.process(failure(2))
        self.assertEqual(engine.process(failure(3)).current_state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.process(success(4)).current_state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.process(success(5)).current_state, HealthState.UNAVAILABLE)
        self.assertEqual(engine.process(success(6)).current_state, HealthState.HEALTHY)

        with self.assertRaises(ValueError):
            HealthPolicy(degraded_after_failures=0)
        with self.assertRaises(ValueError):
            HealthPolicy(degraded_after_failures=3, unavailable_after_failures=2)
        with self.assertRaises(ValueError):
            HealthPolicy(recover_after_successes=0)

    def test_16_sample_validation_rejects_impossible_metadata(self) -> None:
        with self.assertRaises(ValueError):
            HealthSample(
                sample_id="bad-success",
                outcome=ProbeOutcome.SUCCESS,
                completed_at=BASE,
                failure_class=FailureClass.TIMEOUT,
            )
        with self.assertRaises(ValueError):
            HealthSample(
                sample_id="bad-failure",
                outcome=ProbeOutcome.FAILURE,
                completed_at=BASE,
            )
        with self.assertRaises(ValueError):
            HealthSample(
                sample_id="bad-latency",
                outcome=ProbeOutcome.SUCCESS,
                completed_at=BASE,
                latency_ms=-1,
            )


if __name__ == "__main__":
    unittest.main()
