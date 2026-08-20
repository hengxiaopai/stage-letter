from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from api.services.admin_platforms import (
    MANAGEABLE_PLATFORMS,
    PlatformControlAction,
    _target_state,
    _validate_platform,
)


ROOT = Path(__file__).resolve().parents[2]


def test_platform_controls_are_limited_to_the_four_supported_platforms() -> None:
    assert MANAGEABLE_PLATFORMS == {"bilibili", "douyin", "douyu", "huya"}
    assert _validate_platform(" DouYin ") == "douyin"
    with pytest.raises(HTTPException) as exc:
        _validate_platform("gate16_acceptance")
    assert exc.value.status_code == 404


def test_disable_and_enable_have_conservative_health_targets() -> None:
    assert _target_state(PlatformControlAction.DISABLE) == "DISABLED"
    assert _target_state(PlatformControlAction.ENABLE) == "DEGRADED"


def test_admin_platform_control_is_protected_audited_and_has_no_notification_path() -> None:
    router = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    service = (ROOT / "api" / "services" / "admin_platforms.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations" / "versions" / "f52a9d1c4e81_gate52_admin_platform_audit.py").read_text(encoding="utf-8")

    assert 'Depends(require_admin)' in router
    assert 'post("/admin/platforms/{platform}/disable")' in router
    assert 'post("/admin/platforms/{platform}/enable")' in router
    assert "with_for_update()" in service
    assert "AdminPlatformAction(" in service
    assert "notification" not in service.lower()
    assert "admin_platform_actions" in migration


def test_gate52_documentation_freezes_conservative_restore_evidence() -> None:
    document = (ROOT / "GATE-5.md").read_text(encoding="utf-8")
    report = (ROOT / "reports" / "gate52_platform_controls.md").read_text(encoding="utf-8")

    assert "Gate 5.2 — Audited Platform Enable/Disable Controls" in document
    assert "HEALTHY → DISABLED → DEGRADED" in document
    assert "DISABLED → DEGRADED" in report
    assert "no provider call" in document
