from __future__ import annotations

import ast
import unittest
from pathlib import Path

from stage_letter.domain.health import RuntimeHealthState
from stage_letter.domain.live import (
    LiveEventCause,
    LiveEventType,
    LiveStatus,
    SessionOrigin,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryState,
    GrantState,
)


ROOT = Path(__file__).resolve().parents[2]


def _enum_values(relative_path: str, class_name: str) -> set[str]:
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            values: set[str] = set()
            for statement in node.body:
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target = statement.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                    values.add(statement.value.value)
            if not values:
                raise AssertionError(f"no enum values found for {class_name} in {relative_path}")
            return values
    raise AssertionError(f"enum {class_name} not found in {relative_path}")


def _runtime_values(enum_type) -> set[str]:
    return {item.value for item in enum_type}


class Gate0RegressionContractTests(unittest.TestCase):
    """Compare formal Gate 1 vocabulary against accepted Gate 0 oracle source.

    Gate 1 runtime code must not import experiments/*; tests are allowed to read
    oracle source as evidence. Behavioral oracle suites are executed separately
    by scripts/gate1_regression_probe.py.
    """

    def test_gate0b_observation_status_matches_formal_live_status(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0b/state_engine.py", "ObservationStatus"),
            _runtime_values(LiveStatus),
        )

    def test_gate0c_canonical_status_matches_formal_live_status(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0c/platform_health.py", "CanonicalStatus"),
            _runtime_values(LiveStatus),
        )

    def test_gate0b_session_origin_matches_formal_session_origin(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0b/state_engine.py", "SessionOrigin"),
            _runtime_values(SessionOrigin),
        )

    def test_gate0b_event_type_matches_formal_event_type(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0b/state_engine.py", "LiveEventType"),
            _runtime_values(LiveEventType),
        )

    def test_gate0b_event_cause_matches_formal_event_cause(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0b/state_engine.py", "LiveEventCause"),
            _runtime_values(LiveEventCause),
        )

    def test_gate0d_channel_remains_in_formal_delivery_channels(self) -> None:
        self.assertLessEqual(
            _enum_values("experiments/gate0d/notification_truth.py", "Channel"),
            _runtime_values(DeliveryChannel),
        )

    def test_gate0d_grant_state_matches_formal_grant_state(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0d/notification_truth.py", "GrantState"),
            _runtime_values(GrantState),
        )

    def test_gate0d_execution_state_matches_formal_delivery_state(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0d/delivery_retry.py", "ExecutionState"),
            _runtime_values(DeliveryState),
        )

    def test_gate0c_health_state_matches_formal_runtime_health(self) -> None:
        self.assertEqual(
            _enum_values("experiments/gate0c/platform_health.py", "HealthState"),
            _runtime_values(RuntimeHealthState),
        )

    def test_formal_runtime_does_not_import_experiments(self) -> None:
        violations: list[str] = []
        formal_root = ROOT / "stage_letter"
        for path in formal_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                for module in modules:
                    if module == "experiments" or module.startswith("experiments."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{module}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
