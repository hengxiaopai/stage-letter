from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.detection.contracts import PlatformHealthState, PollingTier
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.db.base import Base
from stage_letter.infrastructure.db import models as _formal_models  # noqa: F401
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    unknown_snapshot_for_failure,
)

ROOT = Path(__file__).resolve().parents[2]


class Gate20BoundaryFreezeTests(unittest.TestCase):
    def test_operational_vocabulary_is_frozen(self) -> None:
        self.assertEqual(["hot", "warm", "cold"], [item.value for item in PollingTier])
        self.assertEqual(
            ["HEALTHY", "DEGRADED", "DISABLED"],
            [item.value for item in PlatformHealthState],
        )

    def test_gate1_canonical_base_remains_ten_tables(self) -> None:
        self.assertEqual(10, len(Base.metadata.tables))
        self.assertNotIn("platform_health", Base.metadata.tables)
        self.assertNotIn("probe_runs", Base.metadata.tables)

    def test_existing_physical_detection_storage_is_available_outside_base(self) -> None:
        migration = (ROOT / "migrations" / "versions" / "5354a9ed7741_initial_schema_11_tables.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("op.create_table('platform_health'", migration)
        self.assertIn("op.create_table('probe_runs'", migration)
        self.assertIn("sa.Column('polling_tier'", migration)

    def test_formal_scheduler_does_not_import_legacy_or_notification_runtime(self) -> None:
        path = ROOT / "workers" / "monitoring" / "scheduler.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)

        forbidden_prefixes = (
            "core",
            "platform_adapters",
            "workers.probe",
            "workers.notify",
            "workers.notification",
        )
        self.assertFalse(
            [module for module in modules if module.startswith(forbidden_prefixes)],
            modules,
        )

    def test_provider_probe_persists_observation_before_any_state_interpretation(self) -> None:
        source = (
            ROOT / "stage_letter" / "application" / "services" / "monitoring_probe.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LiveObservation(", source)
        self.assertIn("append_observation", source)
        self.assertNotIn("LiveStateReducer", source)
        self.assertNotIn("LiveTransitionPersistenceApplicationService", source)

    def test_every_provider_failure_kind_stays_unknown_live_truth(self) -> None:
        account = PlatformAccount(
            account_id="101",
            creator_id="201",
            platform="douyin",
            platform_user_id="provider-101",
            enabled=True,
        )
        now = datetime(2026, 8, 20, 4, 30, tzinfo=timezone.utc)
        for kind in ProviderFailureKind:
            with self.subTest(kind=kind):
                snapshot = unknown_snapshot_for_failure(
                    account,
                    observed_at=now,
                    failure=ProviderFailure(kind=kind, source="gate2.test"),
                )
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)

    def test_gate2_document_quarantines_legacy_worker_and_preserves_gate0a_caveat(self) -> None:
        document = (ROOT / "GATE-2.md").read_text(encoding="utf-8")
        self.assertIn("workers/probe/worker.py", document)
        self.assertIn("LEGACY_REFERENCE_ONLY", document)
        self.assertIn("Gate 0A remains DEGRADED", document)
        self.assertIn("435 / 435", document)
        self.assertIn("a63f4b2d9e71", document)


if __name__ == "__main__":
    unittest.main()
