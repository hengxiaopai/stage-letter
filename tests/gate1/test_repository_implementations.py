from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from stage_letter.application.ports import (
    CreatorRepository,
    FollowRepository,
    LiveRepository,
    NotificationRepository,
)
from stage_letter.infrastructure.db.models import (
    LiveEventModel,
    LiveSessionModel,
    NotificationDeliveryModel,
    PlatformAccountModel,
)
from stage_letter.infrastructure.db.repositories.creator import SQLAlchemyCreatorRepository
from stage_letter.infrastructure.db.repositories.follow import SQLAlchemyFollowRepository
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository
from stage_letter.infrastructure.db.repositories.notification import SQLAlchemyNotificationRepository


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "c91e8d2f4a10_gate12_relax_legacy_write_bridges.py"
REPO_ROOT = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories"


def _calls(path: Path, attr: str) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == attr:
                found.append(node.lineno)
    return found


class RepositoryImplementationContractTests(unittest.TestCase):
    def test_four_sqlalchemy_repositories_structurally_implement_ports(self) -> None:
        dummy = object()
        self.assertIsInstance(SQLAlchemyCreatorRepository(dummy), CreatorRepository)  # type: ignore[arg-type]
        self.assertIsInstance(SQLAlchemyFollowRepository(dummy), FollowRepository)  # type: ignore[arg-type]
        self.assertIsInstance(SQLAlchemyLiveRepository(dummy), LiveRepository)  # type: ignore[arg-type]
        self.assertIsInstance(SQLAlchemyNotificationRepository(dummy), NotificationRepository)  # type: ignore[arg-type]

    def test_repository_methods_do_not_commit_or_rollback(self) -> None:
        violations: list[str] = []
        for path in REPO_ROOT.glob("*.py"):
            for method in ("commit", "rollback"):
                for lineno in _calls(path, method):
                    violations.append(f"{path.name}:{lineno}:{method}")
        self.assertEqual([], violations)

    def test_live_observation_lookup_matches_source_scoped_db_identity(self) -> None:
        params = list(inspect.signature(LiveRepository.has_observation).parameters)
        self.assertEqual(
            ["self", "account_id", "source", "observation_id"],
            params,
        )

    def test_fk_dependent_core_live_inserts_flush_pending_orm_parents(self) -> None:
        observation_source = inspect.getsource(SQLAlchemyLiveRepository.append_observation)
        event_source = inspect.getsource(SQLAlchemyLiveRepository.append_event)
        self.assertIn("await self.session.flush()", observation_source)
        self.assertIn("await self.session.flush()", event_source)

    def test_legacy_bridge_columns_are_nullable_in_formal_models(self) -> None:
        self.assertTrue(PlatformAccountModel.__table__.c.anchor_id.nullable)
        self.assertTrue(PlatformAccountModel.__table__.c.canonical_url.nullable)
        self.assertTrue(LiveSessionModel.__table__.c.anchor_id.nullable)
        self.assertTrue(LiveSessionModel.__table__.c.platform.nullable)
        self.assertTrue(LiveSessionModel.__table__.c.state.nullable)
        self.assertTrue(LiveSessionModel.__table__.c.started_at_source.nullable)
        self.assertTrue(LiveEventModel.__table__.c.anchor_id.nullable)
        self.assertTrue(LiveEventModel.__table__.c.confidence.nullable)
        self.assertTrue(LiveEventModel.__table__.c.detected_at.nullable)
        self.assertTrue(NotificationDeliveryModel.__table__.c.notification_job_id.nullable)

    def test_bridge_revision_extends_gate11_head(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "c91e8d2f4a10"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "b63e4f9a1c20"', source)

    def test_bridge_migration_is_non_destructive(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        for forbidden in ("op.drop_table", "op.drop_column", "op.rename_table"):
            self.assertNotIn(forbidden, source)

    def test_bridge_migration_does_not_backfill_fake_legacy_values(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertNotIn("UPDATE platform_accounts", source)
        self.assertNotIn("INSERT INTO anchors", source)
        self.assertNotIn("INSERT INTO notification_jobs", source)
        self.assertNotIn("SET notification_job_id", source)

    def test_bridge_removes_only_obsolete_session_keyed_delivery_uniqueness(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('"uq_nd_user_session_channel"', source)
        self.assertIn("op.drop_constraint", source)
        self.assertNotIn('op.drop_constraint(\n        "uq_g11_delivery_user_event_channel"', source)

    def test_repository_layer_does_not_import_transport_or_legacy_runtime(self) -> None:
        forbidden = ("api", "workers", "core", "platform_adapters", "experiments")
        violations: list[str] = []
        for path in REPO_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                for module in modules:
                    if any(module == p or module.startswith(p + ".") for p in forbidden):
                        violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
