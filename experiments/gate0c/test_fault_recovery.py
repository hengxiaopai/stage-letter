#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

GATE0B_DIR = Path(__file__).resolve().parents[1] / "gate0b"
if str(GATE0B_DIR) not in sys.path:
    sys.path.insert(0, str(GATE0B_DIR))

from state_engine import (  # noqa: E402
    EngineState,
    LiveObservation,
    ObservationStatus,
    StateEngine,
)

from fault_recovery import ScenarioStep, run_scenario  # noqa: E402
from platform_health import (  # noqa: E402
    CanonicalStatus,
    FailureKind,
    HealthState,
    aggregate_health,
)
from poll_policy import PollMode  # noqa: E402


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 17, 16, 0, tzinfo=TZ)


def step(
    number: int,
    status: CanonicalStatus,
    *,
    failure_kind: FailureKind | None = None,
    latency_ms: int = 300,
    started_at: datetime | None = None,
) -> ScenarioStep:
    return ScenarioStep(
        step_id=f"step-{number}",
        started_at=started_at or (BASE + timedelta(seconds=number)),
        status=status,
        latency_ms=latency_ms,
        failure_kind=failure_kind,
    )


class FaultRecoveryGate0C3Tests(unittest.TestCase):
    def test_01_timeout_degrades_then_two_clean_samples_recover(self) -> None:
        records = run_scenario(
            [
                step(1, CanonicalStatus.OFFLINE),
                step(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT),
                step(3, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT),
                step(4, CanonicalStatus.OFFLINE),
                step(5, CanonicalStatus.OFFLINE),
            ]
        )
        self.assertEqual(
            [record.health_after for record in records],
            [
                HealthState.HEALTHY,
                HealthState.HEALTHY,
                HealthState.DEGRADED,
                HealthState.DEGRADED,
                HealthState.HEALTHY,
            ],
        )
        self.assertEqual(records[2].poll_decision.mode, PollMode.CONSERVATIVE)
        self.assertTrue(
            all(
                record.canonical_status is CanonicalStatus.UNKNOWN
                for record in records[1:3]
            )
        )

    def test_02_network_outage_reaches_unavailable_then_recovers(self) -> None:
        records = run_scenario(
            [
                step(1, CanonicalStatus.LIVE),
                step(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
                step(3, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
                step(4, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
                step(5, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
                step(6, CanonicalStatus.LIVE),
                step(7, CanonicalStatus.LIVE),
            ]
        )
        self.assertEqual(records[4].health_after, HealthState.UNAVAILABLE)
        self.assertEqual(records[4].poll_decision.mode, PollMode.RECOVERY_PROBE)
        self.assertEqual(records[4].poll_decision.delay_s, 1440)
        self.assertEqual(records[5].health_after, HealthState.DEGRADED)
        self.assertEqual(records[6].health_after, HealthState.HEALTHY)

    def test_03_parse_failures_never_become_creator_offline(self) -> None:
        records = run_scenario(
            [
                step(1, CanonicalStatus.LIVE),
                step(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.PARSE),
                step(3, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.PARSE),
                step(4, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.PARSE),
                step(5, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.PARSE),
            ]
        )
        self.assertEqual(records[-1].health_after, HealthState.UNAVAILABLE)
        self.assertNotIn(
            CanonicalStatus.OFFLINE,
            [record.canonical_status for record in records[1:]],
        )

    def test_04_rate_limit_enforces_cooldown_without_faking_offline(self) -> None:
        records = run_scenario(
            [
                step(1, CanonicalStatus.LIVE),
                step(2, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.RATE_LIMIT),
            ]
        )
        limited = records[-1]
        self.assertEqual(limited.canonical_status, CanonicalStatus.UNKNOWN)
        self.assertGreaterEqual(limited.poll_decision.delay_s, 600)
        self.assertEqual(limited.poll_decision.minimum_cooldown_s, 600)

    def test_05_auth_and_blocked_are_immediate_unavailable_with_long_cooldown(self) -> None:
        for kind in (FailureKind.AUTH, FailureKind.BLOCKED):
            with self.subTest(kind=kind):
                records = run_scenario(
                    [
                        step(1, CanonicalStatus.OFFLINE),
                        step(2, CanonicalStatus.UNKNOWN, failure_kind=kind),
                    ]
                )
                failed = records[-1]
                self.assertEqual(failed.health_after, HealthState.UNAVAILABLE)
                self.assertEqual(failed.canonical_status, CanonicalStatus.UNKNOWN)
                self.assertGreaterEqual(failed.poll_decision.delay_s, 900)

    def test_06_slow_decisive_live_preserves_live_while_health_degrades(self) -> None:
        records = run_scenario(
            [
                step(1, CanonicalStatus.OFFLINE),
                step(2, CanonicalStatus.LIVE, latency_ms=6000),
            ]
        )
        slow = records[-1]
        self.assertEqual(slow.canonical_status, CanonicalStatus.LIVE)
        self.assertEqual(slow.health_after, HealthState.DEGRADED)
        self.assertEqual(slow.poll_decision.mode, PollMode.CONSERVATIVE)

    def test_07_old_delayed_failure_after_newer_success_is_stale(self) -> None:
        newer_time = BASE + timedelta(seconds=20)
        older_time = BASE + timedelta(seconds=10)
        records = run_scenario(
            [
                step(1, CanonicalStatus.LIVE, started_at=newer_time),
                step(
                    2,
                    CanonicalStatus.UNKNOWN,
                    failure_kind=FailureKind.TIMEOUT,
                    started_at=older_time,
                ),
            ]
        )
        stale = records[-1]
        self.assertTrue(stale.stale)
        self.assertFalse(stale.accepted)
        self.assertEqual(stale.health_after, HealthState.HEALTHY)
        self.assertEqual(stale.consecutive_failures, 0)

    def test_08_mixed_scope_health_is_degraded_not_global_unavailable(self) -> None:
        self.assertEqual(
            aggregate_health([HealthState.HEALTHY, HealthState.UNAVAILABLE]),
            HealthState.DEGRADED,
        )

    def test_09_provider_unknown_faults_do_not_close_gate0b_live_session(self) -> None:
        engine = StateEngine()
        engine.process(
            LiveObservation("b-1", ObservationStatus.OFFLINE, BASE, "gate0c-integration")
        )
        engine.process(
            LiveObservation(
                "b-2",
                ObservationStatus.LIVE,
                BASE + timedelta(seconds=1),
                "gate0c-integration",
            )
        )
        engine.process(
            LiveObservation(
                "b-3",
                ObservationStatus.LIVE,
                BASE + timedelta(seconds=2),
                "gate0c-integration",
            )
        )
        self.assertEqual(engine.state, EngineState.LIVE_CONFIRMED)
        session = engine.open_session
        self.assertIsNotNone(session)
        assert session is not None
        session_id = session.session_id

        fault_records = run_scenario(
            [
                step(10, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.TIMEOUT),
                step(11, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
                step(12, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.PARSE),
                step(13, CanonicalStatus.UNKNOWN, failure_kind=FailureKind.NETWORK),
            ]
        )
        self.assertEqual(fault_records[-1].health_after, HealthState.UNAVAILABLE)

        for index in range(10, 14):
            result = engine.process(
                LiveObservation(
                    f"b-{index}",
                    ObservationStatus.UNKNOWN,
                    BASE + timedelta(seconds=index),
                    "gate0c-integration",
                )
            )
            self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)

        self.assertIsNotNone(engine.open_session)
        assert engine.open_session is not None
        self.assertEqual(engine.open_session.session_id, session_id)
        self.assertTrue(engine.open_session.is_open)

    def test_10_clean_live_after_faults_keeps_same_gate0b_session(self) -> None:
        engine = StateEngine()
        engine.process(LiveObservation("c-1", ObservationStatus.OFFLINE, BASE))
        engine.process(
            LiveObservation("c-2", ObservationStatus.LIVE, BASE + timedelta(seconds=1))
        )
        engine.process(
            LiveObservation("c-3", ObservationStatus.LIVE, BASE + timedelta(seconds=2))
        )
        session = engine.open_session
        assert session is not None
        session_id = session.session_id

        engine.process(
            LiveObservation("c-4", ObservationStatus.UNKNOWN, BASE + timedelta(seconds=3))
        )
        engine.process(
            LiveObservation("c-5", ObservationStatus.UNKNOWN, BASE + timedelta(seconds=4))
        )
        recovered = engine.process(
            LiveObservation("c-6", ObservationStatus.LIVE, BASE + timedelta(seconds=5))
        )
        self.assertEqual(recovered.current_state, EngineState.LIVE_CONFIRMED)
        self.assertIsNotNone(engine.open_session)
        assert engine.open_session is not None
        self.assertEqual(engine.open_session.session_id, session_id)
        self.assertEqual(len(engine.sessions), 1)


if __name__ == "__main__":
    unittest.main()
