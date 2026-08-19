from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORMAL_ROOT = ROOT / "stage_letter"
API_ROOT = ROOT / "api" / "composition.py"
WORKER_ROOT = ROOT / "workers" / "composition.py"
REGRESSION_PROBE = ROOT / "scripts" / "gate12_regression_probe.py"
MAIN_DOC = ROOT / "docs" / "gate1" / "GATE_1_2.md"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append(node.module or "")
    return result


class Gate12AcceptanceContractTests(unittest.TestCase):
    def test_gate12_regression_probe_pins_accepted_oracle_minimums(self) -> None:
        source = REGRESSION_PROBE.read_text(encoding="utf-8")
        self.assertIn('Suite("Gate 0B state/persistence oracle", ROOT / "experiments/gate0b", ".", 37)', source)
        self.assertIn('Suite("Gate 0C health/composition oracle", ROOT / "experiments/gate0c", ".", 65)', source)
        self.assertIn('Suite("Gate 0D notification/delivery oracle", ROOT / "experiments/gate0d", ".", 54)', source)
        self.assertIn('Suite("Gate 0E golden path oracle", ROOT / "experiments/gate0e", ".", 15)', source)
        self.assertIn('Suite("Gate 1 formal contracts", ROOT, "tests/gate1", 111)', source)

    def test_gate12_regression_probe_pins_current_schema_head_and_offline_sql(self) -> None:
        source = REGRESSION_PROBE.read_text(encoding="utf-8")
        self.assertIn('EXPECTED_HEAD = "c91e8d2f4a10"', source)
        self.assertIn('[sys.executable, "-m", "alembic", "heads"]', source)
        self.assertIn('[sys.executable, "-m", "alembic", "upgrade", "head", "--sql"]', source)

    def test_formal_runtime_has_no_inward_dependency_on_outer_or_legacy_packages(self) -> None:
        forbidden = ("api", "workers", "core", "platform_adapters", "experiments")
        violations: list[str] = []
        for path in FORMAL_ROOT.rglob("*.py"):
            for module in _imports(path):
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{module}")
        self.assertEqual([], violations)

    def test_application_layer_remains_infrastructure_and_framework_free(self) -> None:
        forbidden = (
            "stage_letter.infrastructure",
            "sqlalchemy",
            "alembic",
            "asyncpg",
            "fastapi",
            "redis",
            "dramatiq",
            "requests",
            "httpx",
        )
        violations: list[str] = []
        for path in (FORMAL_ROOT / "application").rglob("*.py"):
            for module in _imports(path):
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{module}")
        self.assertEqual([], violations)

    def test_composition_roots_remain_thin_and_do_not_cross_import(self) -> None:
        forbidden = ("stage_letter.domain", "core", "platform_adapters", "experiments")
        for path in (API_ROOT, WORKER_ROOT):
            modules = _imports(path)
            self.assertFalse(
                any(
                    module == prefix or module.startswith(prefix + ".")
                    for module in modules
                    for prefix in forbidden
                ),
                modules,
            )
        self.assertFalse(any(m == "workers" or m.startswith("workers.") for m in _imports(API_ROOT)))
        self.assertFalse(any(m == "api" or m.startswith("api.") for m in _imports(WORKER_ROOT)))

    def test_gate12_main_document_records_final_closed_state_and_gate13_handoff(self) -> None:
        source = MAIN_DOC.read_text(encoding="utf-8")
        self.assertIn("Status: **PASS / CLOSED**", source)
        self.assertIn("Gate 1.2-5  PASS", source)
        self.assertIn("Gate 1.2-6  PASS", source)
        self.assertIn("Gate 1.2   PASS / CLOSED", source)
        self.assertIn("Gate 1.3   CURRENT", source)
        self.assertIn("Gate 0A", source)
        self.assertIn("DEGRADED", source)


if __name__ == "__main__":
    unittest.main()
