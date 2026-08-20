from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gate55_restart_probe_is_read_only_and_checks_fresh_engine_projections() -> None:
    source = (ROOT / "scripts" / "gate55_admin_restart_probe.py").read_text(encoding="utf-8")

    assert 'EXPECTED_HEAD = "f52a9d1c4e81"' in source
    assert "create_async_engine" in source
    assert "await engine.dispose()" in source
    assert "build_system_health" in source
    assert "list_users" in source
    assert "list_subscriptions" in source
    assert "list_deliveries" in source
    assert "build_admin_metrics" in source
    assert '"database_write_performed": False' in source
    assert '"provider_called": False' in source
    assert '"notification_called": False' in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
