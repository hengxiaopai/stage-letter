from __future__ import annotations

import ast
import builtins
import unittest
from pathlib import Path
from unittest.mock import patch

from stage_letter.application.platforms import LivePlatformAdapter
from stage_letter.application.services import (
    MonitoringProbeApplicationService,
    MonitoringTargetApplicationService,
)
from stage_letter.infrastructure.platforms import FORMAL_PLATFORMS
from workers.composition import WorkerServiceBundle, build_worker_services
from workers.monitoring import MonitoringScheduler, MonitoringSchedulerPolicy


ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_PATH = ROOT / "workers" / "composition.py"


class Gate14WorkerWiringContractTests(unittest.TestCase):
    def test_bundle_wires_exact_four_platform_registry(self) -> None:
        bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        self.assertIsInstance(bundle, WorkerServiceBundle)
        self.assertEqual(tuple(sorted(FORMAL_PLATFORMS)), bundle.adapter_registry.platforms())
        self.assertEqual(("bilibili", "douyin", "douyu", "huya"), bundle.adapter_registry.platforms())

    def test_every_registered_adapter_implements_formal_contract(self) -> None:
        bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        for platform in bundle.adapter_registry.platforms():
            with self.subTest(platform=platform):
                adapter = bundle.adapter_registry.get(platform)
                self.assertIsInstance(adapter, LivePlatformAdapter)
                self.assertEqual(platform, getattr(adapter, "platform"))

    def test_probe_uses_same_uow_factory_as_worker_application_services(self) -> None:
        bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        self.assertIsInstance(bundle.monitoring_probe, MonitoringProbeApplicationService)
        factory = bundle.creators._uow_factory
        self.assertIs(factory, bundle.monitoring_targets._uow_factory)
        self.assertIs(factory, bundle.monitoring_probe._uow_factory)

    def test_probe_lookup_is_bound_to_bundle_registry(self) -> None:
        bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        lookup = bundle.monitoring_probe._adapter_lookup
        self.assertIs(getattr(lookup, "__self__", None), bundle.adapter_registry)
        for platform in bundle.adapter_registry.platforms():
            self.assertIs(lookup(platform), bundle.adapter_registry.get(platform))

    def test_scheduler_uses_same_target_and_probe_instances(self) -> None:
        bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        self.assertIsInstance(bundle.monitoring_targets, MonitoringTargetApplicationService)
        self.assertIsInstance(bundle.monitoring_scheduler, MonitoringScheduler)
        self.assertIs(bundle.monitoring_scheduler._targets, bundle.monitoring_targets)
        self.assertIs(bundle.monitoring_scheduler._probes, bundle.monitoring_probe)

    def test_custom_scheduler_policy_is_preserved(self) -> None:
        policy = MonitoringSchedulerPolicy(
            cadence_seconds=45,
            max_concurrency=8,
            per_platform_concurrency=2,
            max_attempts=2,
            base_backoff_seconds=0.5,
            max_backoff_seconds=4,
            page_size=50,
        )
        bundle = build_worker_services(
            lambda: object(),  # type: ignore[arg-type]
            scheduler_policy=policy,
        )
        self.assertIs(bundle.monitoring_scheduler.policy, policy)

    def test_construction_does_not_open_database_session(self) -> None:
        calls = 0

        def session_factory():
            nonlocal calls
            calls += 1
            return object()

        build_worker_services(session_factory)  # type: ignore[arg-type]
        self.assertEqual(0, calls)

    def test_construction_does_not_require_eager_streamget_import(self) -> None:
        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamget" or name.startswith("streamget."):
                raise AssertionError("worker construction must not import streamget eagerly")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guarded_import):
            bundle = build_worker_services(lambda: object())  # type: ignore[arg-type]
        self.assertTrue(bundle.adapter_registry.contains("douyin"))

    def test_each_build_gets_fresh_registry_probe_and_scheduler(self) -> None:
        first = build_worker_services(lambda: object())  # type: ignore[arg-type]
        second = build_worker_services(lambda: object())  # type: ignore[arg-type]
        self.assertIsNot(first.adapter_registry, second.adapter_registry)
        self.assertIsNot(first.monitoring_probe, second.monitoring_probe)
        self.assertIsNot(first.monitoring_scheduler, second.monitoring_scheduler)
        for platform in first.adapter_registry.platforms():
            with self.subTest(platform=platform):
                self.assertIsNot(
                    first.adapter_registry.get(platform),
                    second.adapter_registry.get(platform),
                )

    def test_worker_composition_owns_wiring_not_live_truth_or_legacy_runtime(self) -> None:
        source = COMPOSITION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(COMPOSITION_PATH))
        forbidden = (
            "stage_letter.domain",
            "platform_adapters",
            "experiments",
            "core",
            "api",
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
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("Notification", source)
        self.assertNotIn("LiveStatus.OFFLINE", source)
        self.assertNotIn("room_id", source)
        self.assertNotIn("title", source)


if __name__ == "__main__":
    unittest.main()
