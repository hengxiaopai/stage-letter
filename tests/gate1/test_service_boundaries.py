from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORMAL_ROOT = ROOT / "stage_letter"


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append((node.lineno, node.module or ""))
    return result


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*.py"):
        for lineno, module in _imports(path):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes):
                found.append(f"{path.relative_to(ROOT)}:{lineno}:{module}")
    return found


class ServiceBoundaryContractTests(unittest.TestCase):
    def test_domain_is_innermost_layer(self) -> None:
        forbidden = (
            "stage_letter.application",
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "alembic",
            "asyncpg",
            "fastapi",
            "redis",
            "dramatiq",
            "requests",
            "httpx",
        )
        self.assertEqual([], _violations(FORMAL_ROOT / "domain", forbidden))

    def test_application_does_not_depend_on_infrastructure_or_frameworks(self) -> None:
        forbidden = (
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "alembic",
            "asyncpg",
            "fastapi",
            "redis",
            "dramatiq",
            "requests",
            "httpx",
        )
        self.assertEqual([], _violations(FORMAL_ROOT / "application", forbidden))

    def test_infrastructure_does_not_depend_on_transport_or_legacy_runtime(self) -> None:
        forbidden = (
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
        )
        self.assertEqual([], _violations(FORMAL_ROOT / "infrastructure", forbidden))

    def test_formal_runtime_does_not_import_legacy_top_level_packages(self) -> None:
        forbidden = (
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
        )
        self.assertEqual([], _violations(FORMAL_ROOT, forbidden))

    def test_application_ports_remain_infrastructure_free(self) -> None:
        path = FORMAL_ROOT / "application" / "ports.py"
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
        violations = [
            f"{path.relative_to(ROOT)}:{lineno}:{module}"
            for lineno, module in _imports(path)
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
        ]
        self.assertEqual([], violations)

    def test_legacy_boundary_debt_is_explicitly_present_not_hidden(self) -> None:
        # Gate 1.2-1 does not pretend the pre-formal API/worker implementation is
        # already compliant. These paths are quarantined migration debt and must
        # remain visible until later Gate 1.2 cutover work removes/replaces them.
        expected_legacy = (
            ROOT / "api" / "services",
            ROOT / "workers" / "probe" / "worker.py",
            ROOT / "workers" / "notify" / "in_app.py",
            ROOT / "workers" / "notify" / "wechat.py",
            ROOT / "core",
            ROOT / "platform_adapters",
        )
        missing = [str(path.relative_to(ROOT)) for path in expected_legacy if not path.exists()]
        self.assertEqual([], missing)

    def test_boundary_freeze_document_exists(self) -> None:
        self.assertTrue((ROOT / "docs" / "gate1" / "GATE_1_2_BOUNDARY_FREEZE.md").is_file())


if __name__ == "__main__":
    unittest.main()
