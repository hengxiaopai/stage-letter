from __future__ import annotations

import ast
from pathlib import Path

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)
from stage_letter.domain.notifications import DeliveryChannel
from stage_letter.infrastructure.notifications.wechat import (
    ERR_TEMPLATE_INVALID,
    WeChatRawResponse,
    normalize_wechat_response,
)

ROOT = Path(__file__).resolve().parents[2]


def test_roadmap_orders_notification_engine_after_detection_engine() -> None:
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    gate2 = roadmap.index("Gate 2 — Detection Engine")
    gate3 = roadmap.index("Gate 3 — Notification Engine")
    gate4 = roadmap.index("Gate 4 — 微信小程序")
    assert gate2 < gate3 < gate4


def test_gate30_document_reuses_gate16_instead_of_rebuilding_it() -> None:
    document = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    assert "completion/reconciliation phase" in document
    assert "Gate 1.6" in document
    assert "must not be resent" in document
    assert "b25d4e9c7a12" in document


def test_gate30_document_maps_remaining_notification_gaps() -> None:
    document = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    for phrase in (
        "IN_APP",
        "40037",
        "Grant Intake",
        "Notification Read Model",
        "Anchor Detail Routing Contract",
        "Gate 0A remains DEGRADED",
    ):
        assert phrase in document


def test_existing_wechat_delivery_channel_remains_accepted_baseline() -> None:
    assert DeliveryChannel.WECHAT_SUBSCRIBE.value == "WECHAT_SUBSCRIBE"


def test_wechat_40037_baseline_remains_config_blocked_and_preserves_grant() -> None:
    outcome = normalize_wechat_response(
        WeChatRawResponse(
            http_status=200,
            body={"errcode": ERR_TEMPLATE_INVALID, "errmsg": "template invalid"},
        )
    )
    assert outcome.kind is ProviderOutcomeKind.CONFIG_BLOCKED
    assert outcome.grant_effect is GrantEffect.PRESERVE


def test_wechat_message_contract_already_supports_future_page_routing() -> None:
    fields = WeChatLiveStartMessage.__dataclass_fields__
    assert "page" in fields
    assert fields["page"].default is None


def test_gate30_adds_no_competing_notification_provider_or_live_truth_boundary() -> None:
    gate3 = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    assert "Notification failure never mutates live truth" in gate3
    assert "No blind resend of AMBIGUOUS" in gate3

    provider_tree = ast.parse(
        (ROOT / "stage_letter" / "application" / "notification_providers.py").read_text(
            encoding="utf-8"
        )
    )
    imported_modules = {
        node.module
        for node in ast.walk(provider_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "stage_letter.infrastructure" not in imported_modules
