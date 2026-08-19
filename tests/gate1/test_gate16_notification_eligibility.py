from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.domain.live import LiveEvent, LiveEventCause, LiveEventType
from stage_letter.domain.notification_policy import (
    EligibilityDecision,
    EligibilityReason,
    NotificationTarget,
    build_pending_delivery,
    evaluate_notification_eligibility,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryState,
    GrantState,
)


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "stage_letter" / "domain" / "notification_policy.py"
T0 = datetime(2026, 8, 19, 19, 0, tzinfo=timezone.utc)


def _event(
    *,
    event_type: LiveEventType = LiveEventType.LIVE_STARTED,
    cause: LiveEventCause = LiveEventCause.TRANSITION,
) -> LiveEvent:
    return LiveEvent(
        event_id="live-event:formal-1",
        account_id="101",
        session_id="501",
        event_type=event_type,
        cause=cause,
        occurred_at=T0,
    )


def _target(
    *,
    following: bool = True,
    notification_enabled: bool = True,
    grant_state: GrantState = GrantState.GRANTED,
    account_id: str = "101",
) -> NotificationTarget:
    return NotificationTarget(
        user_id="201",
        account_id=account_id,
        following=following,
        notification_enabled=notification_enabled,
        grant_state=grant_state,
    )


class Gate16NotificationEligibilityTests(unittest.TestCase):
    def test_live_started_transition_follow_enabled_granted_is_eligible(self) -> None:
        decision = evaluate_notification_eligibility(_event(), _target())
        self.assertTrue(decision.eligible)
        self.assertEqual(EligibilityReason.ELIGIBLE, decision.reason)
        self.assertEqual(DeliveryChannel.WECHAT_SUBSCRIBE, decision.channel)

    def test_live_ended_is_not_eligible(self) -> None:
        decision = evaluate_notification_eligibility(
            _event(event_type=LiveEventType.LIVE_ENDED),
            _target(),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(EligibilityReason.WRONG_EVENT_TYPE, decision.reason)

    def test_bootstrap_live_started_is_not_eligible(self) -> None:
        decision = evaluate_notification_eligibility(
            _event(cause=LiveEventCause.BOOTSTRAP_LIVE),
            _target(),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(EligibilityReason.BOOTSTRAP_LIVE, decision.reason)

    def test_not_following_is_not_eligible(self) -> None:
        decision = evaluate_notification_eligibility(
            _event(),
            _target(following=False),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(EligibilityReason.NOT_FOLLOWING, decision.reason)

    def test_disabled_notification_preference_is_not_eligible(self) -> None:
        decision = evaluate_notification_eligibility(
            _event(),
            _target(notification_enabled=False),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(EligibilityReason.NOTIFICATION_DISABLED, decision.reason)

    def test_only_granted_grant_state_is_eligible(self) -> None:
        for grant_state in (GrantState.DENIED, GrantState.UNKNOWN, GrantState.EXHAUSTED):
            with self.subTest(grant_state=grant_state):
                decision = evaluate_notification_eligibility(
                    _event(),
                    _target(grant_state=grant_state),
                )
                self.assertFalse(decision.eligible)
                self.assertEqual(EligibilityReason.GRANT_NOT_GRANTED, decision.reason)

    def test_target_account_must_match_event_account(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_notification_eligibility(
                _event(),
                _target(account_id="999"),
            )

    def test_eligibility_decision_truth_flag_and_reason_cannot_conflict(self) -> None:
        with self.assertRaises(ValueError):
            EligibilityDecision(
                eligible=True,
                reason=EligibilityReason.GRANT_NOT_GRANTED,
                user_id="201",
                live_event_id="live-event:formal-1",
                channel=DeliveryChannel.WECHAT_SUBSCRIBE,
            )
        with self.assertRaises(ValueError):
            EligibilityDecision(
                eligible=False,
                reason=EligibilityReason.ELIGIBLE,
                user_id="201",
                live_event_id="live-event:formal-1",
                channel=DeliveryChannel.WECHAT_SUBSCRIBE,
            )

    def test_eligible_decision_builds_pending_logical_delivery(self) -> None:
        event = _event()
        target = _target()
        decision = evaluate_notification_eligibility(event, target)
        delivery = build_pending_delivery(decision, event, target)
        self.assertIsNotNone(delivery)
        assert delivery is not None
        self.assertEqual("201", delivery.key.user_id)
        self.assertEqual(event.event_id, delivery.key.live_event_id)
        self.assertEqual(DeliveryChannel.WECHAT_SUBSCRIBE, delivery.key.channel)
        self.assertEqual(event.account_id, delivery.account_id)
        self.assertEqual(event.session_id, delivery.session_id)
        self.assertEqual(event.occurred_at, delivery.created_at)
        self.assertEqual(DeliveryState.PENDING, delivery.state)

    def test_ineligible_decision_builds_no_delivery(self) -> None:
        event = _event(event_type=LiveEventType.LIVE_ENDED)
        target = _target()
        decision = evaluate_notification_eligibility(event, target)
        self.assertIsNone(build_pending_delivery(decision, event, target))

    def test_delivery_identity_is_exact_user_event_channel_tuple(self) -> None:
        event = _event()
        target = _target()
        first = build_pending_delivery(
            evaluate_notification_eligibility(event, target),
            event,
            target,
        )
        second = build_pending_delivery(
            evaluate_notification_eligibility(event, target),
            event,
            target,
        )
        assert first is not None and second is not None
        self.assertEqual(first.key, second.key)
        self.assertEqual(
            ("201", "live-event:formal-1", DeliveryChannel.WECHAT_SUBSCRIBE),
            (first.key.user_id, first.key.live_event_id, first.key.channel),
        )

    def test_policy_is_pure_and_does_not_import_provider_persistence_or_experiments(self) -> None:
        tree = ast.parse(POLICY_PATH.read_text(encoding="utf-8"), filename=str(POLICY_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "stage_letter.application",
            "workers",
            "api",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
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

        source = POLICY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("get_live_snapshot", source)
        self.assertNotIn("save_session", source)
        self.assertNotIn("append_event", source)
        self.assertNotIn("access_token", source)
        self.assertNotIn("AppSecret", source)


if __name__ == "__main__":
    unittest.main()
