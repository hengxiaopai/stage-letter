from __future__ import annotations

import inspect
import unittest

from stage_letter.application.ports import (
    CreatorRepository,
    FollowRepository,
    LiveRepository,
    NotificationRepository,
    UnitOfWork,
)


class ApplicationPortContractTests(unittest.TestCase):
    def test_repository_ports_are_protocols(self) -> None:
        for port in (
            CreatorRepository,
            FollowRepository,
            LiveRepository,
            NotificationRepository,
            UnitOfWork,
        ):
            self.assertTrue(getattr(port, "_is_protocol", False), port.__name__)

    def test_repository_io_is_async(self) -> None:
        methods = {
            CreatorRepository: (
                "get_creator",
                "get_profile",
                "get_account",
                "get_account_by_platform_identity",
                "list_enabled_accounts",
                "save_creator",
                "save_profile",
                "save_account",
            ),
            FollowRepository: (
                "get_follow",
                "save_follow",
                "delete_follow",
                "get_notification_preference",
                "save_notification_preference",
            ),
            LiveRepository: (
                "has_observation",
                "get_observation",
                "append_observation",
                "list_monitor_observations",
                "get_latest_observation",
                "acquire_transition_lock",
                "get_open_session",
                "get_session",
                "create_session",
                "save_session",
                "append_event",
                "get_event",
            ),
            NotificationRepository: (
                "get_delivery",
                "create_delivery",
                "save_delivery",
            ),
            UnitOfWork: ("__aenter__", "__aexit__", "commit", "rollback"),
        }
        for port, names in methods.items():
            for name in names:
                self.assertTrue(
                    inspect.iscoroutinefunction(getattr(port, name)),
                    f"{port.__name__}.{name} must be async",
                )

    def test_live_repository_persists_observation_before_state_outputs(self) -> None:
        names = set(LiveRepository.__dict__)
        self.assertIn("append_observation", names)
        self.assertIn("acquire_transition_lock", names)
        self.assertIn("save_session", names)
        self.assertIn("append_event", names)

    def test_notification_repository_uses_delivery_key(self) -> None:
        annotations = inspect.signature(NotificationRepository.get_delivery).parameters
        self.assertEqual(annotations["key"].annotation, "DeliveryKey")

    def test_follow_port_keeps_preferences_separate(self) -> None:
        names = set(FollowRepository.__dict__)
        self.assertIn("save_follow", names)
        self.assertIn("save_notification_preference", names)

    def test_unit_of_work_exposes_atomic_commit_and_rollback(self) -> None:
        names = set(UnitOfWork.__dict__)
        self.assertIn("commit", names)
        self.assertIn("rollback", names)


if __name__ == "__main__":
    unittest.main()
