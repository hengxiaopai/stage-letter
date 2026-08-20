from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from api import admin_security
from api.admin_security import AdminActor, require_admin
from api.routers.admin import render_admin_health_page


ROOT = Path(__file__).resolve().parents[2]


def test_admin_access_is_unavailable_without_server_side_configuration(monkeypatch) -> None:
    monkeypatch.setattr(admin_security.settings, "admin_username", "")
    monkeypatch.setattr(admin_security.settings, "admin_password", "")

    with pytest.raises(HTTPException) as exc:
        require_admin(None)

    assert exc.value.status_code == 503


def test_admin_access_requires_constant_time_matching_basic_credentials(monkeypatch) -> None:
    monkeypatch.setattr(admin_security.settings, "admin_username", "operator")
    monkeypatch.setattr(admin_security.settings, "admin_password", "local-secret")

    with pytest.raises(HTTPException) as exc:
        require_admin(HTTPBasicCredentials(username="operator", password="wrong"))
    assert exc.value.status_code == 401

    actor = require_admin(HTTPBasicCredentials(username="operator", password="local-secret"))
    assert actor == AdminActor(username="operator")


def test_admin_health_page_escapes_snapshot_values_and_stays_read_only() -> None:
    html = render_admin_health_page(
        {
            "api": "HEALTHY",
            "worker": {"healthy": True},
            "timestamp": "2026-08-20T00:00:00+00:00",
            "platforms": {"<platform>": {"state": "<DEGRADED>", "consecutive_failures": 1}},
        },
        AdminActor(username="<operator>"),
    )

    assert "&lt;platform&gt;" in html
    assert "&lt;DEGRADED&gt;" in html
    assert "&lt;operator&gt;" in html
    assert "页面不提供通知操作" in html


def test_admin_routes_are_wired_behind_the_shared_health_snapshot() -> None:
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    router = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")

    assert "app.include_router(admin.router" in main
    assert "Depends(require_admin)" in router
    assert "build_system_health" in router


def test_gate51_documentation_preserves_the_observed_unhealthy_worker() -> None:
    document = (ROOT / "GATE-5.md").read_text(encoding="utf-8")
    report = (ROOT / "reports" / "gate51_admin_health.md").read_text(encoding="utf-8")

    assert "Gate 5.1 — Protected Admin Shell" in document
    assert "worker indicator rendered `False`" in document
    assert "Worker healthy: False" in report
    assert "not an Admin-page failure" in report
