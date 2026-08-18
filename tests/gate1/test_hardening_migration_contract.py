from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "b63e4f9a1c20_gate1_harden_constraints.py"
SOURCE = MIGRATION.read_text(encoding="utf-8")


class HardeningMigrationContractTests(unittest.TestCase):
    def test_revision_extends_expand_head(self) -> None:
        self.assertIn('revision: str = "b63e4f9a1c20"', SOURCE)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "a41f6c2e9b77"', SOURCE)

    def test_observation_status_is_database_constrained(self) -> None:
        self.assertIn("ck_g11_live_observation_status", SOURCE)
        self.assertIn("status IN ('LIVE', 'OFFLINE', 'UNKNOWN')", SOURCE)

    def test_open_session_constraint_uses_ended_at_null(self) -> None:
        self.assertIn("uq_g11_open_session_per_account", SOURCE)
        self.assertIn('postgresql_where=sa.text("ended_at IS NULL")', SOURCE)

    def test_legacy_session_origin_remains_nullable(self) -> None:
        self.assertIn("origin IS NULL OR origin IN ('TRANSITION', 'BOOTSTRAP_LIVE')", SOURCE)
        self.assertNotIn("SET origin =", SOURCE)

    def test_legacy_event_identity_and_cause_are_not_invented(self) -> None:
        self.assertIn("uq_g11_live_event_id", SOURCE)
        self.assertIn("cause IS NULL OR cause IN ('TRANSITION', 'BOOTSTRAP_LIVE')", SOURCE)
        self.assertNotIn("SET event_id =", SOURCE)
        self.assertNotIn("SET cause =", SOURCE)

    def test_delivery_identity_is_user_event_channel(self) -> None:
        self.assertIn("uq_g11_delivery_user_event_channel", SOURCE)
        self.assertIn('["user_id", "live_event_id", "channel"]', SOURCE)

    def test_legacy_wechat_channel_is_deterministically_normalized(self) -> None:
        self.assertIn("SET channel = 'WECHAT_SUBSCRIBE'", SOURCE)
        self.assertIn("WHERE channel = 'wechat'", SOURCE)

    def test_delivery_event_backfill_uses_existing_job_relation(self) -> None:
        self.assertIn("FROM notification_jobs AS nj", SOURCE)
        self.assertIn("nd.notification_job_id = nj.id", SOURCE)
        self.assertIn("SET live_event_id = nj.live_event_id", SOURCE)

    def test_upgrade_has_no_drop_or_destructive_rename(self) -> None:
        upgrade_source = SOURCE.split("def downgrade()", 1)[0]
        self.assertNotIn("op.drop_table", upgrade_source)
        self.assertNotIn("op.drop_column", upgrade_source)
        self.assertNotIn("new_column_name", upgrade_source)

    def test_downgrade_is_forward_only(self) -> None:
        self.assertIn("hardening migration is forward-only", SOURCE)


if __name__ == "__main__":
    unittest.main()
