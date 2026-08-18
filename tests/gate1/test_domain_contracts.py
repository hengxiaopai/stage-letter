from __future__ import annotations

import unittest
from datetime import datetime, timezone

from stage_letter.domain import (
    Creator,
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    Follow,
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveStatus,
    NotificationDelivery,
    NotificationPreference,
    PlatformAccount,
    RuntimeHealthState,
    SessionOrigin,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


class DomainContractTests(unittest.TestCase):
    def test_canonical_live_status_is_exactly_three_states(self) -> None:
        self.assertEqual(
            {item.value for item in LiveStatus},
            {"LIVE", "OFFLINE", "UNKNOWN"},
        )

    def test_unknown_is_not_offline(self) -> None:
        self.assertIsNot(LiveStatus.UNKNOWN, LiveStatus.OFFLINE)

    def test_creator_and_platform_account_are_separate_entities(self) -> None:
        creator = Creator("creator-1")
        account_a = PlatformAccount("account-a", creator.creator_id, "douyin", "u-a")
        account_b = PlatformAccount("account-b", creator.creator_id, "bilibili", "u-b")
        self.assertEqual(account_a.creator_id, account_b.creator_id)
        self.assertNotEqual(account_a.account_id, account_b.account_id)

    def test_follow_and_notification_preference_are_separate(self) -> None:
        follow = Follow("user-1", "creator-1", "account-1")
        preference = NotificationPreference("user-1", "account-1", enabled=False)
        self.assertEqual(follow.account_id, preference.account_id)
        self.assertFalse(preference.enabled)

    def test_bootstrap_live_event_is_distinct_from_transition(self) -> None:
        bootstrap = LiveEvent(
            "event-b",
            "account-1",
            "session-1",
            LiveEventType.LIVE_STARTED,
            LiveEventCause.BOOTSTRAP_LIVE,
            NOW,
        )
        transition = LiveEvent(
            "event-t",
            "account-1",
            "session-2",
            LiveEventType.LIVE_STARTED,
            LiveEventCause.TRANSITION,
            NOW,
        )
        self.assertNotEqual(bootstrap.cause, transition.cause)

    def test_live_observation_requires_durable_identity(self) -> None:
        with self.assertRaises(ValueError):
            LiveObservation("", "account-1", LiveStatus.UNKNOWN, NOW, "streamget")

    def test_session_rejects_negative_time_range(self) -> None:
        with self.assertRaises(ValueError):
            LiveSession(
                "session-1",
                "account-1",
                opened_at=NOW,
                closed_at=NOW.replace(hour=11),
                origin=SessionOrigin.TRANSITION,
            )

    def test_delivery_identity_is_event_based(self) -> None:
        first = DeliveryKey("user-1", "event-1", DeliveryChannel.WECHAT_SUBSCRIBE)
        second = DeliveryKey("user-1", "event-2", DeliveryChannel.WECHAT_SUBSCRIBE)
        self.assertNotEqual(first, second)

    def test_ambiguous_delivery_disallows_blind_retry(self) -> None:
        delivery = NotificationDelivery(
            DeliveryKey("user-1", "event-1", DeliveryChannel.WECHAT_SUBSCRIBE),
            "account-1",
            "session-1",
            NOW,
            state=DeliveryState.AMBIGUOUS,
        )
        self.assertFalse(delivery.allows_blind_retry)
        self.assertFalse(delivery.is_terminal)

    def test_sent_is_terminal_for_logical_delivery(self) -> None:
        delivery = NotificationDelivery(
            DeliveryKey("user-1", "event-1", DeliveryChannel.WECHAT_SUBSCRIBE),
            "account-1",
            "session-1",
            NOW,
            state=DeliveryState.SENT,
        )
        self.assertTrue(delivery.is_terminal)

    def test_runtime_health_excludes_admin_disabled(self) -> None:
        self.assertEqual(
            {item.value for item in RuntimeHealthState},
            {"STARTING", "HEALTHY", "DEGRADED", "UNAVAILABLE"},
        )


if __name__ == "__main__":
    unittest.main()
