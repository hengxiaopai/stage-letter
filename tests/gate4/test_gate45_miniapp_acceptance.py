from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


def test_reminder_status_uses_component_safe_switch_selector() -> None:
    stylesheet = (MINIAPP / "components" / "reminder-status" / "index.wxss").read_text(
        encoding="utf-8"
    )
    markup = (MINIAPP / "components" / "reminder-status" / "index.wxml").read_text(
        encoding="utf-8"
    )

    assert ".rs switch" not in stylesheet
    assert ".rs-switch" in stylesheet
    assert 'class="rs-switch"' in markup


def test_bottom_action_sheet_uses_component_safe_danger_selector() -> None:
    stylesheet = (MINIAPP / "components" / "bottom-action-sheet" / "index.wxss").read_text(
        encoding="utf-8"
    )
    markup = (MINIAPP / "components" / "bottom-action-sheet" / "index.wxml").read_text(
        encoding="utf-8"
    )

    assert '.sheet-row[data-key="danger"]' not in stylesheet
    assert ".sheet-row-danger" in stylesheet
    assert "sheet-row-danger" in markup


def test_filter_tabs_enables_flex_layout_on_scroll_view() -> None:
    markup = (MINIAPP / "components" / "filter-tabs" / "index.wxml").read_text(
        encoding="utf-8"
    )

    assert '<scroll-view scroll-x enable-flex class="ft"' in markup


def test_gate45_real_device_runner_has_its_own_current_head_contract() -> None:
    runner = (ROOT / "scripts" / "gate45_real_device_notification.py").read_text(
        encoding="utf-8"
    )

    assert 'EXPECTED_HEAD = "e34d7a2c1b50"' in runner
    assert "gate16_prepare_real_wechat_event" in runner
    assert "gate16_real_wechat_acceptance" in runner
    assert 'payload["production_approved"] = False' in runner
    assert 'miniprogram_state="developer"' in runner


def test_controlled_real_wechat_sender_includes_canonical_detail_page() -> None:
    sender = (ROOT / "scripts" / "gate16_real_wechat_acceptance.py").read_text(
        encoding="utf-8"
    )

    assert 'page=f"pages/detail/index?id={account.creator_id}"' in sender
    assert "lacks a valid anchor detail target" in sender
    assert "miniprogram_state=args.miniprogram_state" in sender
