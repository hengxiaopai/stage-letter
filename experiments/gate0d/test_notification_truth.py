#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from notification_truth import (
    Channel,
    DeliveryKey,
    DeliveryLedger,
    EligibilityReason,
    EventCause,
    EventType,
    GrantState,
    NotificationEvent,
    NotificationTarget,
    evaluate_eligibility,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 18, 14, 0, tzinfo=TZ)


def event(
    number: int,
    *,
    event_type: EventType = EventType.LIVE_STARTED,
    cause: EventCause = EventCause.TRANSITION,
    account_id: str = "douyin:creator-1",
) -> NotificationEvent:
    return NotificationEvent(
        event_id=f"event-{number}",
        account_id=account_id,
        event_type=event_type,
        cause=cause,
        occurred_at=BASE + timedelta(seconds=number),
        session_id=f"session-{number}",
    )


def target(
    user_id: str = "user-1",
    *,
    account_id: str = "douyin:creator-1",
    following: bool = True,
    notification_enabled: bool = True,
    grant_state: GrantState = GrantState.GRANTED,
) -> NotificationTarget:
    return NotificationTarget(
        user_id=user_id,
        account_id=account_id,
        following=following,
        notification_enabled=notification_enabled,
        grant_state=grant_state,
    )


class NotificationTruthGate0D1Tests(unittest.TestCase):
    def test_01_transition_live_started_is_eligible(self) -> None:
        decision = evaluate_eligibility(event(1), target())
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.ELIGIBLE)

    def test_02_bootstrap_live_is_not_eligible(self) -> None:
        decision = evaluate_eligibility(event(1, cause=EventCause.BOOTSTRAP_LIVE), target())
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.BOOTSTRAP_LIVE)

    def test_03_live_ended_is_not_eligible(self) -> None:
        decision = evaluate_eligibility(event(1, event_type=EventType.LIVE_ENDED), target())
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.WRONG_EVENT_TYPE)

    def test_04_not_following_is_not_eligible(self) -> None:
        decision = evaluate_eligibility(event(1), target(following=False))
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.NOT_FOLLOWING)

    def test_05_notification_preference_disabled_is_not_eligible(self) -> None:
        decision = evaluate_eligibility(event(1), target(notification_enabled=False))
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.NOTIFICATION_DISABLED)

    def test_06_denied_grant_is_not_eligible(self) -> None:
        decision = evaluate_eligibility(event(1), target(grant_state=GrantState.DENIED))
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, EligibilityReason.GRANT_NOT_GRANTED)

    def test_07_unknown_or_exhausted_grant_is_not_eligible(self) -> None:
        for state in (GrantState.UNKNOWN, GrantState.EXHAUSTED):
            with self.subTest(state=state):
                decision = evaluate_eligibility(event(1), target(grant_state=state))
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.reason, EligibilityReason.GRANT_NOT_GRANTED)

    def test_08_eligible_decision_creates_one_pending_delivery(self) -> None:
        ledger = DeliveryLedger()
        e = event(1)
        t = target()
        created = ledger.create_if_eligible(evaluate_eligibility(e, t), e, t)
        self.assertTrue(created.created)
        self.assertFalse(created.duplicate)
        self.assertEqual(ledger.count, 1)

    def test_09_same_user_event_channel_is_idempotent(self) -> None:
        ledger = DeliveryLedger()
        e = event(1)
        t = target()
        decision = evaluate_eligibility(e, t)
        first = ledger.create_if_eligible(decision, e, t)
        second = ledger.create_if_eligible(decision, e, t)
        self.assertTrue(first.created)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.delivery, second.delivery)
        self.assertEqual(ledger.count, 1)

    def test_10_ineligible_decision_creates_no_delivery(self) -> None:
        ledger = DeliveryLedger()
        e = event(1, cause=EventCause.BOOTSTRAP_LIVE)
        t = target()
        result = ledger.create_if_eligible(evaluate_eligibility(e, t), e, t)
        self.assertFalse(result.created)
        self.assertFalse(result.duplicate)
        self.assertIsNone(result.delivery)
        self.assertEqual(ledger.count, 0)

    def test_11_same_event_for_two_users_creates_two_deliveries(self) -> None:
        ledger = DeliveryLedger()
        e = event(1)
        for user_id in ("user-1", "user-2"):
            t = target(user_id)
            result = ledger.create_if_eligible(evaluate_eligibility(e, t), e, t)
            self.assertTrue(result.created)
        self.assertEqual(ledger.count, 2)

    def test_12_two_events_for_same_user_create_two_deliveries(self) -> None:
        ledger = DeliveryLedger()
        t = target()
        for number in (1, 2):
            e = event(number)
            result = ledger.create_if_eligible(evaluate_eligibility(e, t), e, t)
            self.assertTrue(result.created)
        self.assertEqual(ledger.count, 2)

    def test_13_snapshot_restore_preserves_delivery_idempotency(self) -> None:
        ledger = DeliveryLedger()
        e = event(1)
        t = target()
        decision = evaluate_eligibility(e, t)
        ledger.create_if_eligible(decision, e, t)

        restarted = DeliveryLedger.from_snapshot(ledger.snapshot())
        duplicate = restarted.create_if_eligible(decision, e, t)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(restarted.count, 1)
        key = DeliveryKey("user-1", "event-1", Channel.WECHAT_SUBSCRIBE)
        self.assertIsNotNone(restarted.get(key))

    def test_14_account_identity_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_eligibility(event(1), target(account_id="douyin:other"))

    def test_15_invalid_event_or_target_identity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NotificationEvent("", "douyin:creator-1", EventType.LIVE_STARTED, EventCause.TRANSITION, BASE, "s")
        with self.assertRaises(ValueError):
            NotificationTarget("", "douyin:creator-1", True, True, GrantState.GRANTED)

    def test_16_notification_truth_exposes_no_creator_state_mutation(self) -> None:
        ledger = DeliveryLedger()
        self.assertFalse(hasattr(ledger, "close_session"))
        self.assertFalse(hasattr(ledger, "set_live_status"))
        self.assertFalse(hasattr(ledger, "open_session"))


if __name__ == "__main__":
    unittest.main()
