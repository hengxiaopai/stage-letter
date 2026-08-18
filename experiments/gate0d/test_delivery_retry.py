#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from delivery_retry import DeliveryRetryMachine, ExecutionState, RetryPolicy
from notification_truth import Channel, DeliveryKey, GrantState
from provider_result import ProviderOutcome, ProviderResult, normalize_provider_result


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 18, 14, 30, tzinfo=TZ)


def key() -> DeliveryKey:
    return DeliveryKey("user-1", "event-1", Channel.WECHAT_SUBSCRIBE)


def machine(*, policy: RetryPolicy | None = None) -> DeliveryRetryMachine:
    return DeliveryRetryMachine(
        key=key(),
        account_id="douyin:creator-1",
        session_id="session-1",
        grant_state=GrantState.GRANTED,
        policy=policy,
    )


def result(
    outcome: ProviderOutcome,
    *,
    retry_after: int | None = None,
    code: str | None = None,
    message: str | None = None,
):
    return normalize_provider_result(
        ProviderResult(
            outcome,
            provider_code=code,
            provider_message=message,
            retry_after_seconds=retry_after,
        )
    )


class DeliveryRetryGate0D3Tests(unittest.TestCase):
    def test_01_begin_attempt_persists_in_flight_before_send(self) -> None:
        m = machine()
        started = m.begin_attempt(attempt_id="a1", started_at=BASE)
        self.assertTrue(started.started)
        self.assertEqual(m.state, ExecutionState.IN_FLIGHT)
        self.assertEqual(m.attempt_count, 1)
        self.assertIsNone(m.attempts[0].completed_at)

    def test_02_sent_is_terminal_for_delivery_without_inferring_global_grant_exhaustion(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        done = m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.SENT),
            completed_at=BASE + timedelta(seconds=1),
        )
        self.assertEqual(done.state, ExecutionState.SENT)
        self.assertEqual(m.grant_state, GrantState.GRANTED)
        self.assertTrue(m.is_terminal)

    def test_03_sent_delivery_cannot_send_again(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.SENT),
            completed_at=BASE + timedelta(seconds=1),
        )
        again = m.begin_attempt(attempt_id="a2", started_at=BASE + timedelta(seconds=2))
        self.assertFalse(again.started)
        self.assertEqual(m.attempt_count, 1)

    def test_04_user_rejected_is_terminal_and_marks_denied(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.USER_REJECTED),
            completed_at=BASE + timedelta(seconds=1),
        )
        self.assertEqual(m.state, ExecutionState.FAILED_TERMINAL)
        self.assertEqual(m.grant_state, GrantState.DENIED)

    def test_05_grant_invalid_is_terminal_and_marks_exhausted(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.GRANT_INVALID),
            completed_at=BASE + timedelta(seconds=1),
        )
        self.assertEqual(m.state, ExecutionState.FAILED_TERMINAL)
        self.assertEqual(m.grant_state, GrantState.EXHAUSTED)

    def test_06_network_error_schedules_transient_retry(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        completed = BASE + timedelta(seconds=1)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.NETWORK_ERROR),
            completed_at=completed,
        )
        self.assertEqual(m.state, ExecutionState.WAITING_RETRY)
        self.assertEqual(m.next_attempt_at, completed + timedelta(seconds=30))
        self.assertEqual(m.grant_state, GrantState.GRANTED)

    def test_07_transient_retry_backoff_grows_exponentially(self) -> None:
        m = machine()
        t = BASE
        expected_delays = (30, 60, 120)
        for number, expected in enumerate(expected_delays, start=1):
            self.assertTrue(m.begin_attempt(attempt_id=f"a{number}", started_at=t).started)
            completed = t + timedelta(seconds=1)
            m.complete_attempt(
                attempt_id=f"a{number}",
                result=result(ProviderOutcome.NETWORK_ERROR),
                completed_at=completed,
            )
            self.assertEqual(m.next_attempt_at, completed + timedelta(seconds=expected))
            t = m.next_attempt_at

    def test_08_transient_backoff_respects_cap(self) -> None:
        p = RetryPolicy(max_total_attempts=6, transient_base_delay_seconds=30, transient_max_delay_seconds=60)
        m = machine(policy=p)
        t = BASE
        for number in range(1, 4):
            m.begin_attempt(attempt_id=f"a{number}", started_at=t)
            completed = t + timedelta(seconds=1)
            m.complete_attempt(
                attempt_id=f"a{number}",
                result=result(ProviderOutcome.PROVIDER_ERROR),
                completed_at=completed,
            )
            t = m.next_attempt_at
        self.assertEqual(m.next_attempt_at, completed + timedelta(seconds=60))

    def test_09_rate_limit_honors_provider_retry_after(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        completed = BASE + timedelta(seconds=1)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.RATE_LIMITED, retry_after=777),
            completed_at=completed,
        )
        self.assertEqual(m.next_attempt_at, completed + timedelta(seconds=777))

    def test_10_rate_limit_without_retry_after_uses_default_cooldown(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        completed = BASE + timedelta(seconds=1)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.RATE_LIMITED),
            completed_at=completed,
        )
        self.assertEqual(m.next_attempt_at, completed + timedelta(seconds=300))

    def test_11_auth_required_waits_for_explicit_auth_resume(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.AUTH_REQUIRED),
            completed_at=BASE + timedelta(seconds=1),
        )
        self.assertEqual(m.state, ExecutionState.WAITING_AUTH)
        self.assertIsNone(m.next_attempt_at)
        self.assertFalse(m.begin_attempt(attempt_id="a2", started_at=BASE + timedelta(hours=1)).started)
        self.assertTrue(m.resume_after_auth())
        self.assertEqual(m.state, ExecutionState.PENDING)

    def test_12_auth_resume_preserves_grant_and_allows_new_attempt(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.AUTH_REQUIRED),
            completed_at=BASE + timedelta(seconds=1),
        )
        m.resume_after_auth()
        self.assertEqual(m.grant_state, GrantState.GRANTED)
        self.assertTrue(m.begin_attempt(attempt_id="a2", started_at=BASE + timedelta(seconds=2)).started)

    def test_13_template_invalid_waits_for_explicit_config_fix(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.TEMPLATE_INVALID),
            completed_at=BASE + timedelta(seconds=1),
        )
        self.assertEqual(m.state, ExecutionState.BLOCKED_CONFIG)
        self.assertFalse(m.begin_attempt(attempt_id="a2", started_at=BASE + timedelta(days=1)).started)
        self.assertTrue(m.resume_after_config_fix())
        self.assertEqual(m.state, ExecutionState.PENDING)

    def test_14_total_attempt_budget_turns_retryable_failure_terminal(self) -> None:
        m = machine(policy=RetryPolicy(max_total_attempts=2))
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.NETWORK_ERROR),
            completed_at=BASE + timedelta(seconds=1),
        )
        second_start = m.next_attempt_at
        m.begin_attempt(attempt_id="a2", started_at=second_start)
        m.complete_attempt(
            attempt_id="a2",
            result=result(ProviderOutcome.NETWORK_ERROR),
            completed_at=second_start + timedelta(seconds=1),
        )
        self.assertEqual(m.state, ExecutionState.FAILED_TERMINAL)
        self.assertEqual(m.terminal_outcome, ProviderOutcome.NETWORK_ERROR)

    def test_15_restart_preserves_waiting_retry_schedule_and_history(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.NETWORK_ERROR, code="net"),
            completed_at=BASE + timedelta(seconds=1),
        )
        restarted = DeliveryRetryMachine.from_snapshot(m.snapshot())
        self.assertEqual(restarted.state, ExecutionState.WAITING_RETRY)
        self.assertEqual(restarted.next_attempt_at, m.next_attempt_at)
        self.assertEqual(restarted.attempts, m.attempts)

    def test_16_restart_with_in_flight_attempt_becomes_ambiguous_not_retryable(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        restarted = DeliveryRetryMachine.from_snapshot(m.snapshot())
        self.assertEqual(restarted.state, ExecutionState.AMBIGUOUS)
        self.assertTrue(restarted.is_terminal)
        self.assertFalse(
            restarted.begin_attempt(attempt_id="a2", started_at=BASE + timedelta(minutes=10)).started
        )

    def test_17_duplicate_completion_replay_is_idempotent(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        normalized = result(ProviderOutcome.NETWORK_ERROR, code="n1", message="temporary")
        m.complete_attempt(
            attempt_id="a1",
            result=normalized,
            completed_at=BASE + timedelta(seconds=1),
        )
        before = m.snapshot()
        replay = m.complete_attempt(
            attempt_id="a1",
            result=normalized,
            completed_at=BASE + timedelta(seconds=2),
        )
        self.assertTrue(replay.duplicate)
        self.assertEqual(m.snapshot(), before)

    def test_18_retry_cannot_start_before_due_time(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.NETWORK_ERROR),
            completed_at=BASE + timedelta(seconds=1),
        )
        too_early = m.next_attempt_at - timedelta(seconds=1)
        self.assertFalse(m.begin_attempt(attempt_id="a2", started_at=too_early).started)
        self.assertTrue(m.begin_attempt(attempt_id="a2", started_at=m.next_attempt_at).started)

    def test_19_attempt_id_is_globally_unique_within_delivery_runtime(self) -> None:
        m = machine()
        m.begin_attempt(attempt_id="a1", started_at=BASE)
        m.complete_attempt(
            attempt_id="a1",
            result=result(ProviderOutcome.NETWORK_ERROR),
            completed_at=BASE + timedelta(seconds=1),
        )
        with self.assertRaises(ValueError):
            m.begin_attempt(attempt_id="a1", started_at=m.next_attempt_at)

    def test_20_runtime_contract_exposes_no_creator_live_state_fields(self) -> None:
        forbidden = {"status", "live_status", "creator_status", "live_session_state"}
        snapshot_fields = {field.name for field in dataclasses.fields(machine().snapshot())}
        self.assertTrue(forbidden.isdisjoint(snapshot_fields))


if __name__ == "__main__":
    unittest.main()
