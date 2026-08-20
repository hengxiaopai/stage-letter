from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gate5_baseline_freezes_existing_operational_seams_and_admin_gaps() -> None:
    document = (ROOT / "GATE-5.md").read_text(encoding="utf-8")

    for phrase in (
        "Status: IN PROGRESS",
        "603 passed, 173 subtests passed",
        "e34d7a2c1b50",
        "GET /api/v1/system/health",
        "platform_health",
        "No public admin data.",
        "Operational controls are auditable.",
        "Gate 0A remains DEGRADED",
    ):
        assert phrase in document
    assert "5.0** Baseline / Administrative Boundary Freeze. **PASS / CLOSED" in document
    assert "5.1** Protected Admin shell + read-only system/platform health. **PASS / CLOSED" in document
    assert "5.2** Audited platform enable/disable controls. **PASS / CLOSED" in document
    assert "5.3** Protected user, subscription, and notification-delivery inquiry. **PASS / CLOSED" in document
    assert "5.4** Metrics and bounded error aggregation. **PASS / CLOSED" in document
    assert "5.5** Restart-safe administrative end-to-end acceptance. **PASS / CLOSED" in document
    assert "Gate 5 is PASS / CLOSED" in document


def test_roadmap_marks_gate5_closed_and_v1_alpha_preparation_current() -> None:
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    gate4_line = next(line for line in roadmap.splitlines() if line.startswith("Gate 4 — 微信小程序"))
    gate5_line = next(line for line in roadmap.splitlines() if line.startswith("Gate 5 — Admin / Observability"))

    assert "PASS / CLOSED" in gate4_line
    assert "PASS / CLOSED" in gate5_line
    assert "V1 Alpha 内测准备                  🚧 CURRENT" in roadmap


def test_gate5_baseline_keeps_schema_changes_under_forward_only_migrations() -> None:
    migration_files = tuple((ROOT / "migrations" / "versions").glob("*.py"))

    assert migration_files
    gate52_migration = ROOT / "migrations" / "versions" / "f52a9d1c4e81_gate52_admin_platform_audit.py"
    assert gate52_migration in migration_files
    assert "forward-only" in gate52_migration.read_text(encoding="utf-8")
