from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from stage_letter.application.ports import WeChatTemplateRepository
from stage_letter.application.services.notification_enqueue import (
    MultiChannelNotificationEnqueueApplicationService,
)
from stage_letter.application.services.wechat_finalize import (
    WeChatDeliveryFinalizationApplicationService,
)
from stage_letter.application.services.wechat_template import (
    WeChatTemplateRegistryApplicationService,
)
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import LiveEvent, LiveEventCause, LiveEventType
from stage_letter.domain.notification_templates import (
    WeChatTemplateRegistration,
    WeChatTemplateState,
    WeChatTemplateStateSource,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    WeChatGrantLedger,
    claim_delivery,
)
from stage_letter.infrastructure.db.base import Base
from stage_letter.infrastructure.db.repositories.wechat_template import (
    SQLAlchemyWeChatTemplateRepository,
)
from workers.notification_runtime import WeChatNotificationRuntime

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "migrations"
    / "versions"
    / "c32a1d7e9b40_gate32_wechat_template_registry.py"
)
T0 = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 20, 5, 1, tzinfo=timezone.utc)


def _registration(
    state: WeChatTemplateState,
    *,
    source: WeChatTemplateStateSource | None = None,
    updated_by: str = "SYSTEM",
) -> WeChatTemplateRegistration:
    disabled = state is WeChatTemplateState.DISABLED
    return WeChatTemplateRegistration(
        template_id="tpl-live-start",
        state=state,
        state_source=source
        or (
            WeChatTemplateStateSource.PROVIDER_40037
            if disabled
            else WeChatTemplateStateSource.REGISTRATION
        ),
        updated_by=updated_by,
        updated_at=T1,
        disabled_reason="WECHAT_40037_TEMPLATE_INVALID" if disabled else None,
        disabled_at=T1 if disabled else None,
    )


def _pending() -> NotificationDelivery:
    return NotificationDelivery(
        DeliveryKey("201", "live-event:gate32", DeliveryChannel.WECHAT_SUBSCRIBE),
        "101",
        "501",
        T0,
    )


def _event() -> LiveEvent:
    return LiveEvent(
        event_id="live-event:gate32",
        account_id="101",
        session_id="501",
        event_type=LiveEventType.LIVE_STARTED,
        cause=LiveEventCause.TRANSITION,
        occurred_at=T0,
    )


class _UoW:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_disabled_template_requires_complete_disable_metadata() -> None:
    with pytest.raises(ValueError, match="disabled_reason"):
        WeChatTemplateRegistration(
            "tpl",
            WeChatTemplateState.DISABLED,
            WeChatTemplateStateSource.PROVIDER_40037,
            "WECHAT_PROVIDER",
            T0,
            disabled_at=T0,
        )
    with pytest.raises(ValueError, match="cannot retain"):
        WeChatTemplateRegistration(
            "tpl",
            WeChatTemplateState.ENABLED,
            WeChatTemplateStateSource.ADMINISTRATOR,
            "admin",
            T0,
            disabled_reason="old",
            disabled_at=T0,
        )


@pytest.mark.asyncio
async def test_unregistered_template_is_compatibly_enabled() -> None:
    uow = _UoW()
    uow.templates = SimpleNamespace(
        get_wechat_template=AsyncMock(return_value=None)
    )
    service = WeChatTemplateRegistryApplicationService(lambda: uow)  # type: ignore[arg-type]

    assert await service.is_enabled("tpl-live-start")
    uow.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_administrator_explicitly_restores_template() -> None:
    enabled = _registration(
        WeChatTemplateState.ENABLED,
        source=WeChatTemplateStateSource.ADMINISTRATOR,
        updated_by="ops-user",
    )
    uow = _UoW()
    enable = AsyncMock(return_value=enabled)
    uow.templates = SimpleNamespace(enable_by_administrator=enable)
    service = WeChatTemplateRegistryApplicationService(lambda: uow)  # type: ignore[arg-type]

    result = await service.enable_by_administrator(
        "tpl-live-start",
        administrator="ops-user",
        now=T1,
    )

    assert result.enabled
    assert result.state_source is WeChatTemplateStateSource.ADMINISTRATOR
    assert result.disabled_reason is None and result.disabled_at is None
    enable.assert_awaited_once_with(
        "tpl-live-start",
        administrator="ops-user",
        now=T1,
    )
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_template_routes_new_fanout_to_in_app() -> None:
    uow = _UoW()
    uow.live = SimpleNamespace(get_event=AsyncMock(return_value=_event()))
    uow.follows = SimpleNamespace(
        list_follows_for_account=AsyncMock(
            return_value=(Follow("201", "301", "101"),)
        ),
        get_notification_preference=AsyncMock(
            return_value=NotificationPreference("201", "101", True)
        ),
    )
    uow.grants = SimpleNamespace(
        get_wechat_grant=AsyncMock(
            return_value=WeChatGrantLedger("201", "tpl-live-start", 2, 0)
        )
    )
    uow.templates = SimpleNamespace(
        get_wechat_template=AsyncMock(
            return_value=_registration(WeChatTemplateState.DISABLED)
        )
    )
    uow.notifications = SimpleNamespace(create_delivery=AsyncMock(return_value=True))
    service = MultiChannelNotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

    result = await service.enqueue_live_event(
        event_id="live-event:gate32",
        template_id="tpl-live-start",
    )

    assert result.created == 1
    delivery = uow.notifications.create_delivery.await_args.args[0]
    assert delivery.key.channel is DeliveryChannel.IN_APP


@pytest.mark.asyncio
async def test_40037_disables_template_in_finalization_transaction() -> None:
    claimed = claim_delivery(_pending(), now=T0)
    disabled = _registration(WeChatTemplateState.DISABLED)
    uow = _UoW()
    uow.notifications = SimpleNamespace(
        lock_delivery=AsyncMock(return_value=claimed),
        get_delivery=AsyncMock(return_value=claimed),
        save_delivery=AsyncMock(),
    )
    uow.grants = SimpleNamespace(consume_wechat_grant=AsyncMock())
    disable = AsyncMock(return_value=disabled)
    uow.templates = SimpleNamespace(disable_from_40037=disable)
    service = WeChatDeliveryFinalizationApplicationService(
        lambda: uow,  # type: ignore[arg-type]
    )

    result = await service.finalize(
        claimed,
        template_id="tpl-live-start",
        outcome=ProviderOutcome(
            ProviderOutcomeKind.CONFIG_BLOCKED,
            GrantEffect.PRESERVE,
            provider_code="40037",
        ),
        now=T1,
    )

    assert result.delivery.state is DeliveryState.BLOCKED_CONFIG
    assert result.template_registration == disabled
    disable.assert_awaited_once_with("tpl-live-start", now=T1)
    uow.grants.consume_wechat_grant.assert_not_awaited()
    uow.notifications.save_delivery.assert_awaited_once()
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_disable_failure_refuses_partial_delivery_commit() -> None:
    claimed = claim_delivery(_pending(), now=T0)
    uow = _UoW()
    uow.notifications = SimpleNamespace(
        lock_delivery=AsyncMock(return_value=claimed),
        get_delivery=AsyncMock(return_value=claimed),
        save_delivery=AsyncMock(),
    )
    uow.grants = SimpleNamespace(consume_wechat_grant=AsyncMock())
    uow.templates = SimpleNamespace(
        disable_from_40037=AsyncMock(side_effect=RuntimeError("registry write failed"))
    )
    service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="registry write failed"):
        await service.finalize(
            claimed,
            template_id="tpl-live-start",
            outcome=ProviderOutcome(
                ProviderOutcomeKind.CONFIG_BLOCKED,
                GrantEffect.PRESERVE,
                provider_code="40037",
            ),
            now=T1,
        )

    uow.notifications.save_delivery.assert_not_awaited()
    uow.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_40037_failure_does_not_disable_template() -> None:
    claimed = claim_delivery(_pending(), now=T0)
    uow = _UoW()
    uow.notifications = SimpleNamespace(
        lock_delivery=AsyncMock(return_value=claimed),
        get_delivery=AsyncMock(return_value=claimed),
        save_delivery=AsyncMock(),
    )
    uow.grants = SimpleNamespace(consume_wechat_grant=AsyncMock())
    disable = AsyncMock()
    uow.templates = SimpleNamespace(disable_from_40037=disable)
    service = WeChatDeliveryFinalizationApplicationService(
        lambda: uow,  # type: ignore[arg-type]
    )

    await service.finalize(
        claimed,
        template_id="tpl-live-start",
        outcome=ProviderOutcome(
            ProviderOutcomeKind.TERMINAL_FAILURE,
            GrantEffect.PRESERVE,
            provider_code="40003",
        ),
        now=T1,
    )

    disable.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_template_blocks_queued_wechat_before_provider() -> None:
    claimed = claim_delivery(_pending(), now=T0)
    blocked = NotificationDelivery(
        claimed.key,
        claimed.account_id,
        claimed.session_id,
        claimed.created_at,
        state=DeliveryState.BLOCKED_CONFIG,
        attempt=claimed.attempt,
        error_code="TEMPLATE_DISABLED",
    )
    fallback = NotificationDelivery(
        DeliveryKey("201", "live-event:gate32", DeliveryChannel.IN_APP),
        "101",
        "501",
        T0,
    )
    runtime = object.__new__(WeChatNotificationRuntime)
    runtime._template_id = "tpl-live-start"
    runtime._delivery_service = SimpleNamespace(
        claim_next_due=AsyncMock(return_value=claimed),
        mark_blocked_config=AsyncMock(return_value=blocked),
    )
    runtime._template_service = SimpleNamespace(
        is_enabled=AsyncMock(return_value=False)
    )
    runtime._fallback_service = SimpleNamespace(
        ensure_for_wechat=AsyncMock(
            return_value=SimpleNamespace(delivery=fallback)
        )
    )
    runtime._get_openid = AsyncMock(
        side_effect=AssertionError("recipient lookup must not run")
    )
    runtime._attempt_service = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("provider must not run"))
    )

    result = await runtime.run_once(now=T1)

    assert result.action == "BLOCKED_CONFIG"
    assert result.in_app_fallback == fallback
    runtime._attempt_service.execute.assert_not_awaited()


def test_migration_extends_gate25_without_expanding_canonical_base() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "c32a1d7e9b40"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "b25d4e9c7a12"' in source
    assert '"wechat_notification_templates"' in source
    assert "ck_g32_template_disabled_metadata" in source
    assert "PROVIDER_40037" in source
    assert "wechat_notification_templates" not in Base.metadata.tables


def test_gate32_document_freezes_template_scope_and_recovery() -> None:
    document = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    for phrase in (
        "wechat_notification_templates",
        "missing registry row is compatibly treated as enabled",
        "Only normalized WeChat provider code `40037`",
        "enable_by_administrator",
        "scripts/gate32_template_admin.py enable",
        "cannot disable Douyin, Bilibili, Huya, or Douyu",
    ):
        assert phrase in document


def test_repository_uses_conflict_safe_state_transitions() -> None:
    assert isinstance(
        SQLAlchemyWeChatTemplateRepository(object()),  # type: ignore[arg-type]
        WeChatTemplateRepository,
    )
    disable = inspect.getsource(SQLAlchemyWeChatTemplateRepository.disable_from_40037)
    update = inspect.getsource(SQLAlchemyWeChatTemplateRepository._set_state)
    assert "PROVIDER_40037" in disable
    assert "WECHAT_40037_TEMPLATE_INVALID" in disable
    assert "on_conflict_do_update" in update


def test_template_service_has_no_platform_or_live_truth_dependency() -> None:
    path = (
        ROOT
        / "stage_letter"
        / "application"
        / "services"
        / "wechat_template.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = ("platform_adapters", "workers", "api", "stage_letter.domain.live")
    imports = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        for module in modules:
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                imports.append(module)
    assert imports == []
