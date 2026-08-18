"""Gate 1.1-3 SQLAlchemy persistence-model contracts."""

from __future__ import annotations

import unittest

from sqlalchemy import UniqueConstraint

from stage_letter.infrastructure.db.base import Base
from stage_letter.infrastructure.db.models import (
    FollowModel,
    LiveEventModel,
    LiveObservationModel,
    LiveSessionModel,
    NotificationDeliveryModel,
    PlatformAccountModel,
)


def _unique_column_sets(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


class PersistenceModelContractTests(unittest.TestCase):
    def test_formal_metadata_contains_exact_ten_domain_tables(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "users",
                "creators",
                "creator_profiles",
                "platform_accounts",
                "follows",
                "notification_preferences",
                "live_observations",
                "live_sessions",
                "live_events",
                "notification_deliveries",
            },
        )

    def test_platform_account_has_creator_owner_and_no_canonical_status_column(self) -> None:
        columns = PlatformAccountModel.__table__.c
        self.assertIn("creator_id", columns)
        self.assertNotIn("last_status", columns)
        self.assertNotIn("runtime_health", columns)

    def test_follow_identity_is_user_plus_platform_account(self) -> None:
        uniques = _unique_column_sets(FollowModel.__table__)
        self.assertIn(("user_id", "platform_account_id"), uniques)

    def test_live_observation_has_stable_source_scoped_identity(self) -> None:
        uniques = _unique_column_sets(LiveObservationModel.__table__)
        self.assertIn(
            ("platform_account_id", "source", "observation_id"),
            uniques,
        )
        self.assertIn("status", LiveObservationModel.__table__.c)
        self.assertIn("source_started_at", LiveObservationModel.__table__.c)

    def test_live_session_has_partial_unique_open_account_index(self) -> None:
        indexes = {index.name: index for index in LiveSessionModel.__table__.indexes}
        index = indexes["uq_g11_open_session_per_account"]
        self.assertTrue(index.unique)
        self.assertEqual(
            tuple(column.name for column in index.columns),
            ("platform_account_id",),
        )
        where = str(index.dialect_options["postgresql"]["where"])
        self.assertIn("ended_at IS NULL", where)

    def test_live_event_persists_type_and_cause_separately(self) -> None:
        columns = LiveEventModel.__table__.c
        self.assertIn("event_type", columns)
        self.assertIn("cause", columns)
        self.assertIn("event_id", columns)
        self.assertIn("occurred_at", columns)

    def test_delivery_identity_is_user_event_channel(self) -> None:
        uniques = _unique_column_sets(NotificationDeliveryModel.__table__)
        self.assertIn(("user_id", "live_event_id", "channel"), uniques)
        self.assertNotIn(("user_id", "live_session_id", "channel"), uniques)

    def test_delivery_state_column_can_persist_full_gate0d_vocabulary(self) -> None:
        length = NotificationDeliveryModel.__table__.c.state.type.length
        self.assertIsNotNone(length)
        self.assertGreaterEqual(length, len("FAILED_TERMINAL"))
        self.assertIn("in_flight_at", NotificationDeliveryModel.__table__.c)
        self.assertIn("next_attempt_at", NotificationDeliveryModel.__table__.c)


if __name__ == "__main__":
    unittest.main()
