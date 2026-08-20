from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_roadmap_orders_mini_program_after_notification_engine() -> None:
    roadmap = _read(ROOT / "ROADMAP.md")
    gate3 = roadmap.index("Gate 3 — Notification Engine")
    gate4 = roadmap.index("Gate 4 — 微信小程序")
    gate5 = roadmap.index("Gate 5 — Admin / Observability")
    assert gate3 < gate4 < gate5
    gate4_line = next(line for line in roadmap.splitlines() if line.startswith("Gate 4 — 微信小程序"))
    gate5_line = next(line for line in roadmap.splitlines() if line.startswith("Gate 5 — Admin / Observability"))
    assert "PASS / CLOSED" in gate4_line
    assert "PASS / CLOSED" in gate5_line


def test_gate40_documents_reused_foundation_and_remaining_gaps() -> None:
    document = _read(ROOT / "GATE-4.md")
    for phrase in (
        "556 passed, 173 subtests passed",
        "e34d7a2c1b50",
        "DEV_OPENID",
        "raw `openid`",
        "Developer Tools",
        "Gate 0A remains DEGRADED",
    ):
        assert phrase in document


def test_native_project_declares_core_surfaces_and_detail_route() -> None:
    manifest = json.loads(_read(MINIAPP / "app.json"))
    assert manifest["pages"] == [
        "pages/home/index",
        "pages/add/index",
        "pages/subscriptions/index",
        "pages/profile/index",
        "pages/detail/index",
    ]
    for page in manifest["pages"]:
        for suffix in ("js", "json", "wxml", "wxss"):
            assert (MINIAPP / f"{page}.{suffix}").is_file()


def test_pages_use_existing_api_services_instead_of_competing_mock_truth() -> None:
    expected_imports = {
        "pages/home/index.js": ("services/lives", "services/subscriptions"),
        "pages/add/index.js": ("services/subscriptions", "services/notifications"),
        "pages/subscriptions/index.js": ("services/subscriptions",),
        "pages/profile/index.js": ("services/notifications",),
        "pages/detail/index.js": ("services/anchors",),
    }
    for relative_path, imports in expected_imports.items():
        source = _read(MINIAPP / relative_path)
        for imported in imports:
            assert imported in source
        assert "mockData" not in source


def test_fixed_dev_identity_was_an_explicit_unaccepted_gate41_gap() -> None:
    gate4 = _read(ROOT / "GATE-4.md")
    assert "real WeChat login was not yet\n   accepted" in gate4
    assert "4.1** WeChat Login + Client Identity Boundary" in gate4


def test_grant_ui_uses_user_action_and_exact_intake_contract() -> None:
    add_page = _read(MINIAPP / "pages/add/index.js")
    profile_page = _read(MINIAPP / "pages/profile/index.js")
    notification_service = _read(MINIAPP / "services/notifications.js")
    assert "wx.requestSubscribeMessage" in add_page
    assert "wx.requestSubscribeMessage" in profile_page
    assert "requestGrant(openid, res)" in add_page
    assert "requestGrant(openid, res)" in profile_page
    assert "decision: grantResults[templateId]" in notification_service
    assert "data: { request_id: durableRequestId, results }" in notification_service
    assert "accept_count" not in notification_service


def test_static_detail_route_does_not_claim_device_click_or_read() -> None:
    profile_page = _read(MINIAPP / "pages/profile/index.js")
    gate4 = _read(ROOT / "GATE-4.md")
    assert "pages/detail/index?id=" in profile_page
    assert "wx.navigateTo" in profile_page
    assert "not device-click\n   evidence" in gate4
    assert "Provider accepted is not device receipt, click, or read" in gate4
