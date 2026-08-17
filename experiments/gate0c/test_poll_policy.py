#!/usr/bin/env python3
from __future__ import annotations

import unittest

from platform_health import FailureKind, HealthState
from poll_policy import (
    PollContext,
    PollMode,
    PollPolicyConfig,
    decide_poll,
)


class PollPolicyGate0C2Tests(unittest.TestCase):
    def test_01_healthy_uses_normal_cadence(self) -> None:
        decision = decide_poll(PollContext(HealthState.HEALTHY))
        self.assertEqual(decision.delay_s, 60)
        self.assertEqual(decision.mode, PollMode.NORMAL)
        self.assertEqual(decision.backoff_step, 0)

    def test_02_degraded_uses_conservative_cadence(self) -> None:
        decision = decide_poll(PollContext(HealthState.DEGRADED))
        self.assertEqual(decision.delay_s, 120)
        self.assertEqual(decision.mode, PollMode.CONSERVATIVE)

    def test_03_unavailable_backoff_grows_exponentially(self) -> None:
        delays = [
            decide_poll(
                PollContext(
                    HealthState.UNAVAILABLE,
                    consecutive_failures=failure_count,
                )
            ).delay_s
            for failure_count in (1, 2, 3, 4)
        ]
        self.assertEqual(delays, [180, 360, 720, 1440])

    def test_04_unavailable_backoff_is_capped(self) -> None:
        decision = decide_poll(
            PollContext(HealthState.UNAVAILABLE, consecutive_failures=10)
        )
        self.assertEqual(decision.delay_s, 1800)
        self.assertEqual(decision.base_delay_s, 1800)
        self.assertTrue(decision.capped)
        self.assertEqual(decision.mode, PollMode.RECOVERY_PROBE)

    def test_05_rate_limit_enforces_minimum_cooldown(self) -> None:
        decision = decide_poll(
            PollContext(
                HealthState.DEGRADED,
                failure_kind=FailureKind.RATE_LIMIT,
                consecutive_failures=2,
                jitter_unit=-1.0,
            )
        )
        self.assertEqual(decision.minimum_cooldown_s, 600)
        self.assertEqual(decision.delay_s, 600)

    def test_06_auth_and_blocked_never_tight_loop(self) -> None:
        for kind in (FailureKind.AUTH, FailureKind.BLOCKED):
            with self.subTest(kind=kind):
                decision = decide_poll(
                    PollContext(
                        HealthState.UNAVAILABLE,
                        failure_kind=kind,
                        consecutive_failures=1,
                        jitter_unit=-1.0,
                    )
                )
                self.assertEqual(decision.minimum_cooldown_s, 900)
                self.assertGreaterEqual(decision.delay_s, 900)

    def test_07_bounded_jitter_never_violates_minimum_cooldown(self) -> None:
        config = PollPolicyConfig(jitter_fraction=0.25)
        negative = decide_poll(
            PollContext(
                HealthState.HEALTHY,
                failure_kind=FailureKind.RATE_LIMIT,
                jitter_unit=-1.0,
            ),
            config,
        )
        positive = decide_poll(
            PollContext(
                HealthState.HEALTHY,
                failure_kind=FailureKind.RATE_LIMIT,
                jitter_unit=1.0,
            ),
            config,
        )
        self.assertGreaterEqual(negative.delay_s, config.rate_limit_min_cooldown_s)
        self.assertGreaterEqual(positive.delay_s, config.rate_limit_min_cooldown_s)

    def test_08_deterministic_jitter_makes_decisions_reproducible(self) -> None:
        context = PollContext(HealthState.HEALTHY, jitter_unit=0.37)
        first = decide_poll(context)
        second = decide_poll(context)
        self.assertEqual(first, second)

    def test_09_healthy_state_resets_unavailable_backoff(self) -> None:
        unavailable = decide_poll(
            PollContext(HealthState.UNAVAILABLE, consecutive_failures=8)
        )
        healthy = decide_poll(
            PollContext(HealthState.HEALTHY, consecutive_failures=8)
        )
        self.assertEqual(unavailable.delay_s, 1800)
        self.assertEqual(healthy.delay_s, 60)
        self.assertEqual(healthy.backoff_step, 0)
        self.assertFalse(healthy.capped)

    def test_10_policy_has_no_creator_live_state_output(self) -> None:
        decision = decide_poll(PollContext(HealthState.UNAVAILABLE))
        self.assertFalse(hasattr(decision, "status"))
        self.assertFalse(hasattr(decision, "canonical_status"))
        self.assertFalse(hasattr(decision, "live_status"))

    def test_11_invalid_policy_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PollPolicyConfig(healthy_interval_s=0)
        with self.assertRaises(ValueError):
            PollPolicyConfig(
                unavailable_base_interval_s=300,
                unavailable_max_interval_s=200,
            )
        with self.assertRaises(ValueError):
            PollPolicyConfig(jitter_fraction=-0.01)
        with self.assertRaises(ValueError):
            PollPolicyConfig(jitter_fraction=0.51)

    def test_12_same_snapshot_inputs_produce_same_decision(self) -> None:
        context_a = PollContext(
            health_state=HealthState.UNAVAILABLE,
            failure_kind=FailureKind.NETWORK,
            consecutive_failures=4,
            jitter_unit=-0.25,
        )
        context_b = PollContext(
            health_state=HealthState.UNAVAILABLE,
            failure_kind=FailureKind.NETWORK,
            consecutive_failures=4,
            jitter_unit=-0.25,
        )
        self.assertEqual(decide_poll(context_a), decide_poll(context_b))

    def test_13_starting_route_uses_separate_probe_cadence(self) -> None:
        decision = decide_poll(PollContext(HealthState.STARTING))
        self.assertEqual(decision.delay_s, 30)
        self.assertEqual(decision.mode, PollMode.NORMAL)

    def test_14_jitter_is_bounded_around_non_cooldown_base(self) -> None:
        config = PollPolicyConfig(healthy_interval_s=100, jitter_fraction=0.10)
        low = decide_poll(
            PollContext(HealthState.HEALTHY, jitter_unit=-1.0),
            config,
        )
        high = decide_poll(
            PollContext(HealthState.HEALTHY, jitter_unit=1.0),
            config,
        )
        self.assertEqual(low.delay_s, 90)
        self.assertEqual(high.delay_s, 110)

    def test_15_positive_jitter_cannot_escape_unavailable_backoff_cap(self) -> None:
        config = PollPolicyConfig(
            unavailable_base_interval_s=100,
            unavailable_max_interval_s=400,
            jitter_fraction=0.50,
        )
        decision = decide_poll(
            PollContext(
                HealthState.UNAVAILABLE,
                consecutive_failures=4,
                jitter_unit=1.0,
            ),
            config,
        )
        self.assertEqual(decision.base_delay_s, 400)
        self.assertEqual(decision.delay_s, 400)
        self.assertTrue(decision.capped)

    def test_16_invalid_poll_context_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PollContext(HealthState.HEALTHY, consecutive_failures=-1)
        with self.assertRaises(ValueError):
            PollContext(HealthState.HEALTHY, jitter_unit=1.01)


if __name__ == "__main__":
    unittest.main()
