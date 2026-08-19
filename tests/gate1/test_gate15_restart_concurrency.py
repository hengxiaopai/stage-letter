from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from stage_letter.application.ports import LiveRepository
from stage_letter.application.services.live_transition import (
    LiveTransitionPersistenceApplicationService,
)
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


ROOT = Path(__file__).resolve().parents[2]
TRANSITION_SERVICE = ROOT / "stage_letter" / "application" / "services" / "live_transition.py"
PROBE = ROOT / "scripts" / "gate15_restart_concurrency_probe.py"


class Gate15RestartConcurrencyContractTests(unittest.TestCase):
    def test_live_repository_exposes_async_transition_lock(self) -> None:
        self.assertIn("acquire_transition_lock", LiveRepository.__dict__)
        self.assertTrue(
            inspect.iscoroutinefunction(LiveRepository.acquire_transition_lock)
        )

    def test_sqlalchemy_transition_lock_is_transaction_scoped_and_account_keyed(self) -> None:
        source = inspect.getsource(SQLAlchemyLiveRepository.acquire_transition_lock)
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertIn('parse_persistence_id(account_id, field="account_id")', source)
        self.assertIn('{"lock_key": -account_pk}', source)

    def test_sqlalchemy_transition_lock_never_commits_or_rolls_back_itself(self) -> None:
        source = inspect.getsource(SQLAlchemyLiveRepository.acquire_transition_lock)
        self.assertNotIn("commit(", source)
        self.assertNotIn("rollback(", source)

    def test_transition_service_locks_before_durable_and_event_decisions(self) -> None:
        source = inspect.getsource(LiveTransitionPersistenceApplicationService.apply)
        lock_at = source.index("acquire_transition_lock")
        durable_at = source.index("get_observation")
        event_at = source.index("get_event")
        self.assertLess(lock_at, durable_at)
        self.assertLess(durable_at, event_at)

    def test_transition_service_remains_infrastructure_free(self) -> None:
        tree = ast.parse(
            TRANSITION_SERVICE.read_text(encoding="utf-8"),
            filename=str(TRANSITION_SERVICE),
        )
        forbidden = (
            "stage_letter.infrastructure",
            "sqlalchemy",
            "workers",
            "api",
            "platform_adapters",
            "experiments",
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

    def test_postgres_probe_requires_current_migration_and_formal_worker_bundle(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn('EXPECTED_HEAD = "d14e7c9a5b30"', source)
        self.assertIn("build_worker_services", source)
        self.assertIn("live_observation_consumer.consume", source)

    def test_postgres_probe_concurrently_consumes_one_decisive_observation(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn("asyncio.gather", source)
        self.assertGreaterEqual(source.count("observations[2].observation_id"), 3)
        self.assertIn('"concurrent_same_session"', source)
        self.assertIn('"concurrent_same_event"', source)

    def test_postgres_probe_crosses_runtime_restart_boundaries(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("await engine.dispose()"), 2)
        self.assertGreaterEqual(source.count("build_worker_services(sessions)"), 3)
        self.assertIn('"restart_open_reused_existing"', source)
        self.assertIn('"restart_close_reused_existing"', source)

    def test_postgres_probe_cross_checks_live_reducer_state_with_open_db_graph(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn("EngineState.LIVE_CONFIRMED", source)
        self.assertIn("open_reconstruction.snapshot.session_open", source)
        self.assertIn("open_counts == (1, 1, 1, 1, 0)", source)
        self.assertIn('"open_state_matches_db"', source)

    def test_postgres_probe_cross_checks_offline_reducer_state_with_closed_db_graph(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn("EngineState.OFFLINE_CONFIRMED", source)
        self.assertIn("not final_reconstruction.snapshot.session_open", source)
        self.assertIn("final_counts == (1, 2, 0, 1, 1)", source)
        self.assertIn('"final_state_matches_db"', source)

    def test_postgres_probe_preserves_pending_offline_and_same_session_close(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn("not first_offline.emitted_transition", source)
        self.assertIn('"first_offline_read_only"', source)
        self.assertIn('"same_session_closed"', source)

    def test_postgres_probe_disclaims_exactly_once_and_production_approval(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        self.assertIn('"worker_exactly_once_claimed": False', source)
        self.assertIn('"provider_exactly_once_claimed": False', source)
        self.assertIn('"production_approved": False', source)


if __name__ == "__main__":
    unittest.main()
