from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stage_letter.application.services.in_app_delivery import (
    InAppDeliveryApplicationService,
    InAppFallbackApplicationService,
    requires_in_app_fallback,
)
from stage_letter.application.services.notification_delivery import (
    NotificationDeliveryApplicationService,
)
from stage_letter.application.services.notification_enqueue import (
    MultiChannelNotificationEnqueueApplicationService,
)
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import LiveEvent, LiveEventCause, LiveEventType
from stage_letter.domain.notification_policy import (
    NotificationTarget,
    evaluate_notification_eligibility,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    GrantState,
    NotificationDelivery,
    WeChatGrantLedger,
    claim_delivery,
    mark_delivery_ambiguous,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    schedule_delivery_retry,
)
from workers.notification_composition import build_in_app_notification_runtime
from workers.notification_runtime import (
    InAppNotificationRuntime,
    WeChatNotificationRuntime,
)

T0 = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def _event() -> LiveEvent:
    return LiveEvent(
        event_id="live-event:gate31",
        account_id="101",
        session_id="501",
        event_type=LiveEventType.LIVE_STARTED,
        cause=LiveEventCause.TRANSITION,
        occurred_at=T0,
    )


def _delivery(
    channel: DeliveryChannel = DeliveryChannel.WECHAT_SUBSCRIBE,
) -> NotificationDelivery:
    return NotificationDelivery(
        key=DeliveryKey("201", "live-event:gate31", channel),
        account_id="101",
        session_id="501",
        created_at=T0,
    )


class _UoW:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.notifications = SimpleNamespace()
        self.live = SimpleNamespace(get_event=AsyncMock(return_value=_event()))
        self.follows = SimpleNamespace(
            list_follows_for_account=AsyncMock(
                return_value=(Follow("201", "301", "101"),)
            ),
            get_notification_preference=AsyncMock(
                return_value=NotificationPreference("201", "101", True)
            ),
        )
        self.grants = SimpleNamespace(get_wechat_grant=AsyncMock(return_value=None))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_in_app_eligibility_does_not_require_wechat_grant() -> None:
    target = NotificationTarget("201", "101", True, True, GrantState.EXHAUSTED)
    decision = evaluate_notification_eligibility(
        _event(),
        target,
        channel=DeliveryChannel.IN_APP,
    )
    assert decision.eligible
    assert decision.channel is DeliveryChannel.IN_APP


@pytest.mark.asyncio
async def test_missing_grant_routes_to_durable_in_app_delivery() -> None:
    uow = _UoW()
    uow.notifications.create_delivery = AsyncMock(return_value=True)
    service = MultiChannelNotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

    result = await service.enqueue_live_event(
        event_id="live-event:gate31",
        template_id="tpl-live-start",
    )

    assert result.created == 1
    delivery = uow.notifications.create_delivery.await_args.args[0]
    assert delivery.key.channel is DeliveryChannel.IN_APP
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_positive_grant_keeps_wechat_as_preferred_channel() -> None:
    uow = _UoW()
    uow.grants.get_wechat_grant.return_value = WeChatGrantLedger(
        "201", "tpl-live-start", 2, 0
    )
    uow.notifications.create_delivery = AsyncMock(return_value=True)
    service = MultiChannelNotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

    await service.enqueue_live_event(
        event_id="live-event:gate31",
        template_id="tpl-live-start",
    )

    delivery = uow.notifications.create_delivery.await_args.args[0]
    assert delivery.key.channel is DeliveryChannel.WECHAT_SUBSCRIBE


@pytest.mark.asyncio
async def test_fallback_is_separate_and_idempotent() -> None:
    source = mark_delivery_blocked_config(
        claim_delivery(_delivery(), now=T0),
        now=T0,
        error_code="40037",
    )
    stored: dict[DeliveryKey, NotificationDelivery] = {}
    uow = _UoW()

    async def create(delivery):
        if delivery.key in stored:
            return False
        stored[delivery.key] = delivery
        return True

    async def get(key):
        return stored.get(key)

    uow.notifications.create_delivery = AsyncMock(side_effect=create)
    uow.notifications.get_delivery = AsyncMock(side_effect=get)
    service = InAppFallbackApplicationService(lambda: uow)  # type: ignore[arg-type]

    first = await service.ensure_for_wechat(source)
    second = await service.ensure_for_wechat(source)

    assert first is not None and first.created
    assert second is not None and not second.created
    assert first.delivery.key.channel is DeliveryChannel.IN_APP
    assert first.delivery.key.user_id == source.key.user_id
    assert first.delivery.key.live_event_id == source.key.live_event_id
    assert len(stored) == 1
    uow.commit.assert_awaited_once()


def test_fallback_matrix_excludes_success_and_active_retry() -> None:
    claimed = claim_delivery(_delivery(), now=T0)
    fallback_states = (
        mark_delivery_waiting_auth(claimed, now=T0),
        mark_delivery_blocked_config(claimed, now=T0),
        mark_delivery_failed_terminal(claimed, now=T0),
        mark_delivery_ambiguous(claimed, now=T0),
    )
    for delivery in fallback_states:
        assert requires_in_app_fallback(delivery)

    assert not requires_in_app_fallback(mark_delivery_sent(claimed, now=T0))
    retry = schedule_delivery_retry(claimed, now=T0, delay_seconds=10)
    assert not requires_in_app_fallback(retry)


@pytest.mark.asyncio
async def test_in_app_delivery_is_published_atomically_without_provider() -> None:
    pending = _delivery(DeliveryChannel.IN_APP)
    uow = _UoW()
    uow.notifications.list_due_delivery_keys = AsyncMock(return_value=(pending.key,))
    uow.notifications.lock_delivery = AsyncMock(return_value=pending)
    uow.notifications.save_delivery = AsyncMock()
    service = InAppDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

    sent = await service.deliver_next(now=T0)

    assert sent is not None
    assert sent.state is DeliveryState.SENT
    assert sent.sent_at == T0
    uow.notifications.list_due_delivery_keys.assert_awaited_once_with(
        T0,
        limit=100,
        channel=DeliveryChannel.IN_APP,
    )
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_in_app_runtime_exposes_idle_and_sent_actions() -> None:
    runtime = object.__new__(InAppNotificationRuntime)
    runtime._delivery_service = SimpleNamespace(
        deliver_next=AsyncMock(side_effect=[None, _delivery(DeliveryChannel.IN_APP)])
    )

    idle = await runtime.run_once(now=T0)
    sent = await runtime.run_once(now=T0)

    assert idle.action == "IDLE" and idle.delivery is None
    assert sent.action == "SENT"
    assert sent.delivery is not None
    assert sent.delivery.key.channel is DeliveryChannel.IN_APP


def test_in_app_composition_requires_no_wechat_credentials_or_provider() -> None:
    bundle = build_in_app_notification_runtime(lambda: None)  # type: ignore[arg-type]
    assert isinstance(bundle.runtime, InAppNotificationRuntime)


@pytest.mark.asyncio
async def test_wechat_runtime_creates_fallback_after_terminal_outcome() -> None:
    claimed = claim_delivery(_delivery(), now=T0)
    failed = mark_delivery_failed_terminal(claimed, now=T0, error_code="TERMINAL")
    fallback = _delivery(DeliveryChannel.IN_APP)
    runtime = object.__new__(WeChatNotificationRuntime)
    runtime._delivery_service = SimpleNamespace(
        claim_next_due=AsyncMock(return_value=claimed)
    )
    runtime._get_openid = AsyncMock(return_value="openid")
    runtime._build_message = AsyncMock(return_value=object())
    runtime._attempt_service = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                delivery=failed,
                provider_outcome=None,
                grant_consumed=False,
            )
        )
    )
    ensure = AsyncMock(
        return_value=SimpleNamespace(delivery=fallback, created=True)
    )
    runtime._fallback_service = SimpleNamespace(ensure_for_wechat=ensure)

    result = await runtime.run_once(now=T0)

    ensure.assert_awaited_once_with(failed)
    assert result.action == DeliveryState.FAILED_TERMINAL.value
    assert result.in_app_fallback == fallback


@pytest.mark.asyncio
async def test_wechat_claim_service_filters_out_in_app_channel() -> None:
    uow = _UoW()
    uow.notifications.list_due_delivery_keys = AsyncMock(return_value=())
    service = NotificationDeliveryApplicationService(
        lambda: uow,  # type: ignore[arg-type]
        channel=DeliveryChannel.WECHAT_SUBSCRIBE,
    )

    assert await service.claim_next_due(now=T0) is None
    uow.notifications.list_due_delivery_keys.assert_awaited_once_with(
        T0,
        limit=100,
        channel=DeliveryChannel.WECHAT_SUBSCRIBE,
    )


def test_gate31_document_freezes_fallback_boundaries_without_migration() -> None:
    document = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    for phrase in (
        "DeliveryChannel.IN_APP",
        "Missing or exhausted grant",
        "WAITING_AUTH",
        "BLOCKED_CONFIG",
        "FAILED_TERMINAL",
        "AMBIGUOUS",
        "workers/notify/in_app.py",
        "b25d4e9c7a12",
    ):
        assert phrase in document


def test_gate31_extends_formal_channels_without_rewriting_gate0d_evidence() -> None:
    experiment = (
        ROOT / "experiments" / "gate0d" / "notification_truth.py"
    ).read_text(encoding="utf-8")
    assert 'WECHAT_SUBSCRIBE = "WECHAT_SUBSCRIBE"' in experiment
    assert 'IN_APP = "IN_APP"' not in experiment
    assert DeliveryChannel.IN_APP.value == "IN_APP"


def test_fallback_service_has_no_provider_or_live_truth_dependency() -> None:
    path = (
        ROOT
        / "stage_letter"
        / "application"
        / "services"
        / "in_app_delivery.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = (
        "stage_letter.infrastructure.notifications",
        "platform_adapters",
        "workers",
        "api",
        "httpx",
        "requests",
    )
    imported = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        for module in modules:
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                imported.append(module)
    assert imported == []
    source = path.read_text(encoding="utf-8")
    assert "save_session" not in source
    assert "append_event" not in source
