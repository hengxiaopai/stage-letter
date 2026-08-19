from __future__ import annotations

import ast
import unittest
from pathlib import Path

from api.composition import ApiServiceBundle, build_api_services
from stage_letter.application.services import (
    CreatorApplicationService,
    FollowApplicationService,
    LiveObservationApplicationService,
    MonitoringTargetApplicationService,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from workers.composition import WorkerServiceBundle, build_worker_services


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "api" / "composition.py"
WORKER_ROOT = ROOT / "workers" / "composition.py"
API_MAIN = ROOT / "api" / "main.py"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


class CompositionRootContractTests(unittest.TestCase):
    def test_api_root_builds_only_formal_application_services(self) -> None:
        session_factory = lambda: object()  # not entered; construction-only contract
        bundle = build_api_services(session_factory)  # type: ignore[arg-type]
        self.assertIsInstance(bundle, ApiServiceBundle)
        self.assertIsInstance(bundle.creators, CreatorApplicationService)
        self.assertIsInstance(bundle.follows, FollowApplicationService)
        self.assertIsInstance(bundle.live_observations, LiveObservationApplicationService)

    def test_worker_root_builds_only_formal_application_services(self) -> None:
        session_factory = lambda: object()
        bundle = build_worker_services(session_factory)  # type: ignore[arg-type]
        self.assertIsInstance(bundle, WorkerServiceBundle)
        self.assertIsInstance(bundle.creators, CreatorApplicationService)
        self.assertIsInstance(bundle.follows, FollowApplicationService)
        self.assertIsInstance(bundle.live_observations, LiveObservationApplicationService)
        self.assertIsInstance(bundle.monitoring_targets, MonitoringTargetApplicationService)

    def test_api_services_share_one_uow_factory_contract(self) -> None:
        session_factory = lambda: object()
        bundle = build_api_services(session_factory)  # type: ignore[arg-type]
        factory = bundle.creators._uow_factory
        self.assertIs(factory, bundle.follows._uow_factory)
        self.assertIs(factory, bundle.live_observations._uow_factory)
        self.assertIsInstance(factory(), SQLAlchemyUnitOfWork)

    def test_worker_services_share_one_uow_factory_contract(self) -> None:
        session_factory = lambda: object()
        bundle = build_worker_services(session_factory)  # type: ignore[arg-type]
        factory = bundle.creators._uow_factory
        self.assertIs(factory, bundle.follows._uow_factory)
        self.assertIs(factory, bundle.live_observations._uow_factory)
        self.assertIs(factory, bundle.monitoring_targets._uow_factory)
        self.assertIsInstance(factory(), SQLAlchemyUnitOfWork)

    def test_composition_roots_do_not_import_domain_or_legacy_runtime(self) -> None:
        forbidden = ("stage_letter.domain", "core", "platform_adapters", "experiments")
        violations: list[str] = []
        for path in (API_ROOT, WORKER_ROOT):
            for module in _imports(path):
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.name}:{module}")
        self.assertEqual([], violations)

    def test_api_and_worker_composition_roots_do_not_depend_on_each_other(self) -> None:
        self.assertNotIn("workers", _imports(API_ROOT))
        self.assertNotIn("api", _imports(WORKER_ROOT))

    def test_api_main_exposes_formal_service_bundle_without_rewriting_legacy_routes(self) -> None:
        source = API_MAIN.read_text(encoding="utf-8")
        self.assertIn("from api.composition import build_api_services", source)
        self.assertIn("app.state.stage_letter_services = build_api_services(async_session)", source)
        self.assertIn("app.include_router(subscriptions.router", source)
        self.assertIn("app.include_router(lives.router", source)


if __name__ == "__main__":
    unittest.main()
