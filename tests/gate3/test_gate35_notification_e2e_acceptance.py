from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stage_letter.application.services.in_app_delivery import (
    requires_in_app_fallback,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
    mark_delivery_ambiguous,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    recover_delivery_as_ambiguous,
    schedule_delivery_retry,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=2)


def _pending(channel: DeliveryChannel = DeliveryChannel.WECHAT_SUBSCRIBE):
    return NotificationDelivery(
        DeliveryKey("20", "gate35-event", channel),
        "30",
        "40",
        T0,
    )


@pytest.mark.parametrize(
    "finish",
    (
        lambda claimed: mark_delivery_waiting_auth(claimed, now=T1),
        lambda claimed: mark_delivery_blocked_config(claimed, now=T1),
        lambda claimed: mark_delivery_failed_terminal(claimed, now=T1),
        lambda claimed: mark_delivery_ambiguous(claimed, now=T1),
    ),
)
def test_all_concluded_wechat_failures_require_in_app_fallback(finish) -> None:
    concluded = finish(claim_delivery(_pending(), now=T0))
    assert requires_in_app_fallback(concluded)


def test_active_retry_and_sent_wechat_do_not_fallback() -> None:
    claimed = claim_delivery(_pending(), now=T0)
    retry = schedule_delivery_retry(claimed, now=T0, delay_seconds=30)
    sent = mark_delivery_sent(claimed, now=T1)
    assert not requires_in_app_fallback(retry)
    assert not requires_in_app_fallback(sent)


def test_restart_recovery_is_ambiguous_and_never_due_for_blind_retry() -> None:
    stale = claim_delivery(_pending(), now=T0)
    recovered = recover_delivery_as_ambiguous(stale, now=T1)
    assert recovered.state is DeliveryState.AMBIGUOUS
    assert not recovered.allows_blind_retry
    assert requires_in_app_fallback(recovered)


def test_in_app_delivery_cannot_recursively_create_fallback() -> None:
    claimed = claim_delivery(_pending(DeliveryChannel.IN_APP), now=T0)
    sent = mark_delivery_sent(claimed, now=T1)
    assert not requires_in_app_fallback(sent)


def test_gate35_probe_composes_existing_formal_services_without_provider() -> None:
    source = (ROOT / "scripts" / "gate35_notification_e2e_probe.py").read_text(
        encoding="utf-8"
    )
    assert "MultiChannelNotificationEnqueueApplicationService" in source
    assert "asyncio.gather" in source
    assert "recover_stale_in_flight" in source
    assert "InAppFallbackApplicationService" in source
    assert "NotificationHistoryApplicationService" in source
    assert '"provider_called": False' in source
    assert "WeChatNotificationRuntime(" not in source


def test_gate35_adds_no_schema_or_exactly_once_claim() -> None:
    migrations = tuple((ROOT / "migrations" / "versions").glob("*gate35*"))
    source = (ROOT / "scripts" / "gate35_notification_e2e_probe.py").read_text(
        encoding="utf-8"
    )
    assert migrations == ()
    assert '"notification_exactly_once_claimed": False' in source
    assert '"worker_exactly_once_claimed": False' in source
    assert '"user_read_claimed": False' in source


def test_gate3_closure_and_gate4_handoff_are_frozen() -> None:
    gate = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "# Gate 3 — Notification Engine\n\nStatus: PASS / CLOSED" in gate
    assert "Gate 3 is **PASS / CLOSED**" in gate
    assert "Gate 4.0" in gate and "is now current" in gate
    assert "Gate 3  Notification Engine  ✅ PASS / CLOSED" in readme
    assert "Gate 4  微信小程序             🚧 4.0 CURRENT" in readme
    assert "真实点击/页面交互属于 Gate 4" in roadmap
