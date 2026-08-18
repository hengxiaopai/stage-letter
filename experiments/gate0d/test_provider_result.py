#!/usr/bin/env python3
from __future__ import annotations

import unittest

from notification_truth import GrantState
from provider_result import (
    GrantEffect,
    NormalizedProviderResult,
    ProviderOutcome,
    ProviderResult,
    RetryClass,
    apply_grant_effect,
    normalize_provider_result,
)


class ProviderResultGate0D2Tests(unittest.TestCase):
    def norm(self, outcome: ProviderOutcome, **kwargs) -> NormalizedProviderResult:
        return normalize_provider_result(ProviderResult(outcome=outcome, **kwargs))

    def test_01_sent_is_terminal_success_and_consumes_one_without_inferring_exhaustion(self) -> None:
        result = self.norm(ProviderOutcome.SENT, provider_code="0")
        self.assertTrue(result.success)
        self.assertTrue(result.terminal_for_delivery)
        self.assertFalse(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.NONE)
        self.assertEqual(result.grant_effect, GrantEffect.CONSUME_ONE)
        self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.GRANTED)

    def test_02_user_rejected_is_terminal_and_marks_denied(self) -> None:
        result = self.norm(ProviderOutcome.USER_REJECTED)
        self.assertFalse(result.success)
        self.assertTrue(result.terminal_for_delivery)
        self.assertFalse(result.retryable)
        self.assertEqual(result.grant_effect, GrantEffect.MARK_DENIED)
        self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.DENIED)

    def test_03_grant_invalid_is_terminal_and_marks_exhausted(self) -> None:
        result = self.norm(ProviderOutcome.GRANT_INVALID)
        self.assertTrue(result.terminal_for_delivery)
        self.assertFalse(result.retryable)
        self.assertEqual(result.grant_effect, GrantEffect.MARK_EXHAUSTED)
        self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.EXHAUSTED)

    def test_04_auth_required_requires_auth_refresh_not_blind_terminal_failure(self) -> None:
        result = self.norm(ProviderOutcome.AUTH_REQUIRED)
        self.assertFalse(result.terminal_for_delivery)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.AFTER_AUTH)
        self.assertEqual(result.grant_effect, GrantEffect.KEEP)

    def test_05_template_invalid_is_config_blocked_and_not_automatically_retryable(self) -> None:
        result = self.norm(ProviderOutcome.TEMPLATE_INVALID)
        self.assertFalse(result.success)
        self.assertFalse(result.terminal_for_delivery)
        self.assertFalse(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.AFTER_CONFIG_FIX)
        self.assertEqual(result.grant_effect, GrantEffect.KEEP)

    def test_06_rate_limited_requires_cooldown(self) -> None:
        result = self.norm(ProviderOutcome.RATE_LIMITED, retry_after_seconds=600)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.AFTER_COOLDOWN)
        self.assertEqual(result.retry_after_seconds, 600)

    def test_07_network_error_is_transient_retryable(self) -> None:
        result = self.norm(ProviderOutcome.NETWORK_ERROR)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.TRANSIENT)
        self.assertEqual(result.grant_effect, GrantEffect.KEEP)

    def test_08_provider_error_is_transient_retryable_at_this_boundary(self) -> None:
        result = self.norm(ProviderOutcome.PROVIDER_ERROR)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_class, RetryClass.TRANSIENT)

    def test_09_retryable_failure_keeps_existing_grant_truth(self) -> None:
        for outcome in (
            ProviderOutcome.AUTH_REQUIRED,
            ProviderOutcome.RATE_LIMITED,
            ProviderOutcome.NETWORK_ERROR,
            ProviderOutcome.PROVIDER_ERROR,
        ):
            result = self.norm(outcome)
            self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.GRANTED)

    def test_10_template_invalid_keeps_user_grant_truth(self) -> None:
        result = self.norm(ProviderOutcome.TEMPLATE_INVALID)
        self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.GRANTED)

    def test_11_provider_code_and_message_are_preserved_as_diagnostics(self) -> None:
        result = self.norm(
            ProviderOutcome.NETWORK_ERROR,
            provider_code="transport-1",
            provider_message="temporary failure",
        )
        self.assertEqual(result.provider_code, "transport-1")
        self.assertEqual(result.provider_message, "temporary failure")

    def test_12_same_input_is_deterministic(self) -> None:
        raw = ProviderResult(
            outcome=ProviderOutcome.RATE_LIMITED,
            provider_code="rate",
            retry_after_seconds=300,
        )
        self.assertEqual(normalize_provider_result(raw), normalize_provider_result(raw))

    def test_13_negative_retry_after_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProviderResult(
                outcome=ProviderOutcome.RATE_LIMITED,
                retry_after_seconds=-1,
            )

    def test_14_sent_cannot_carry_retry_after(self) -> None:
        with self.assertRaises(ValueError):
            self.norm(ProviderOutcome.SENT, retry_after_seconds=1)

    def test_15_terminal_user_or_grant_failures_cannot_carry_retry_after(self) -> None:
        for outcome in (ProviderOutcome.USER_REJECTED, ProviderOutcome.GRANT_INVALID):
            with self.assertRaises(ValueError):
                self.norm(outcome, retry_after_seconds=1)

    def test_16_provider_result_contract_exposes_no_creator_live_state_fields(self) -> None:
        forbidden = {
            "live_status",
            "canonical_status",
            "creator_status",
            "session_state",
            "close_session",
            "open_session",
        }
        self.assertTrue(forbidden.isdisjoint(set(NormalizedProviderResult.__dataclass_fields__)))

    def test_17_auth_failure_does_not_revoke_user_grant(self) -> None:
        result = self.norm(ProviderOutcome.AUTH_REQUIRED)
        self.assertEqual(apply_grant_effect(GrantState.GRANTED, result), GrantState.GRANTED)

    def test_18_success_and_failure_outcomes_are_mutually_explicit(self) -> None:
        sent = self.norm(ProviderOutcome.SENT)
        rejected = self.norm(ProviderOutcome.USER_REJECTED)
        self.assertTrue(sent.success)
        self.assertFalse(rejected.success)
        self.assertNotEqual(sent.grant_effect, rejected.grant_effect)


if __name__ == "__main__":
    unittest.main()
