"""Static acceptance contracts for the Gate 1.1 EXPAND Alembic revision."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "a41f6c2e9b77_gate1_expand_formal_domain.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("gate11_expand", MIGRATION)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Gate 1.1 EXPAND migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExpandMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_migration()
        cls.upgrade_source = inspect.getsource(cls.module.upgrade).lower()

    def test_revision_extends_existing_head(self):
        self.assertEqual(self.module.revision, "a41f6c2e9b77")
        self.assertEqual(self.module.down_revision, "e98c1011d830")

    def test_upgrade_is_expand_only_no_legacy_drop_or_rename(self):
        self.assertNotIn("op.drop_", self.upgrade_source)
        self.assertNotIn("op.rename_", self.upgrade_source)

    def test_formal_new_tables_are_created(self):
        for table in {
            "creators",
            "creator_profiles",
            "follows",
            "notification_preferences",
            "live_observations",
        }:
            self.assertIn(f'"{table}"', self.upgrade_source)

    def test_no_historical_live_observation_is_fabricated(self):
        self.assertNotIn("insert into live_observations", self.upgrade_source)

    def test_anchor_to_creator_backfill_is_deterministic(self):
        self.assertIn("insert into creators", self.upgrade_source)
        self.assertIn("set creator_id = anchor_id", self.upgrade_source)

    def test_follow_and_preference_backfills_use_legacy_subscription_facts(self):
        self.assertIn("insert into follows", self.upgrade_source)
        self.assertIn("insert into notification_preferences", self.upgrade_source)
        self.assertIn("from user_subscriptions", self.upgrade_source)

    def test_source_started_at_backfill_requires_explicit_platform_provenance(self):
        self.assertIn("set source_started_at = started_at", self.upgrade_source)
        self.assertIn("started_at_source = 'platform'", self.upgrade_source)

    def test_event_cause_and_event_identity_are_not_invented(self):
        self.assertNotIn("set cause =", self.upgrade_source)
        self.assertNotIn("set event_id =", self.upgrade_source)

    def test_delivery_event_backfill_uses_existing_job_foreign_key(self):
        self.assertIn("set live_event_id = nj.live_event_id", self.upgrade_source)
        self.assertIn("from notification_jobs as nj", self.upgrade_source)
        self.assertIn("nd.notification_job_id = nj.id", self.upgrade_source)

    def test_upgrade_does_not_reclassify_live_truth(self):
        self.assertNotIn("set last_status", self.upgrade_source)
        self.assertNotIn("unknown", self.upgrade_source.replace("no historical", ""))


if __name__ == "__main__":
    unittest.main()
