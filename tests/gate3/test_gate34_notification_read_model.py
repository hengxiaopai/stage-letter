from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stage_letter.application.services.notification_history import (
    NotificationHistoryApplicationService,
)
from stage_letter.domain.notification_history import (
    AnchorDetailTarget,
    NotificationHistoryEntry,
)
from stage_letter.domain.notifications import DeliveryChannel, DeliveryState
from stage_letter.infrastructure.db.base import Base
from workers.notification_runtime import WeChatNotificationRuntime

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def _entry(delivery_id: int) -> NotificationHistoryEntry:
    return NotificationHistoryEntry(
        delivery_id=delivery_id,
        user_id="20",
        anchor_id="30",
        account_id="40",
        live_event_id=f"event-{delivery_id}",
        session_id="50",
        display_name="主播",
        avatar_url="https://example.invalid/avatar.png",
        platform="bilibili",
        started_at=T0,
        ended_at=None,
        channel=DeliveryChannel.IN_APP,
        state=DeliveryState.SENT,
        created_at=T0,
        sent_at=T0,
        error_code=None,
    )


class _UoW:
    def __init__(self, rows=()) -> None:
        self.notifications = SimpleNamespace(
            list_history_for_user=AsyncMock(return_value=rows)
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Provider:
    async def send(self, message):
        raise AssertionError("provider must not be called while building a message")


@pytest.mark.asyncio
async def test_history_uses_stable_delivery_id_keyset_cursor() -> None:
    uow = _UoW((_entry(9), _entry(8), _entry(7)))
    service = NotificationHistoryApplicationService(lambda: uow)  # type: ignore[arg-type]

    page = await service.list_for_user("20", limit=2, cursor="10")

    assert [item.delivery_id for item in page.items] == [9, 8]
    assert page.next_cursor == "8"
    uow.notifications.list_history_for_user.assert_awaited_once_with(
        "20", before_delivery_id=10, limit=3
    )


@pytest.mark.asyncio
async def test_history_rejects_offset_or_malformed_cursor() -> None:
    service = NotificationHistoryApplicationService(lambda: _UoW())  # type: ignore[arg-type]
    for cursor in ("0", "-1", "offset:20", "abc"):
        with pytest.raises(ValueError, match="cursor"):
            await service.list_for_user("20", cursor=cursor)


def test_anchor_detail_target_is_shared_miniapp_and_api_contract() -> None:
    target = AnchorDetailTarget("30")
    assert target.miniapp_path == "pages/detail/index?id=30"
    assert target.api_path == "/api/v1/anchors/30"


@pytest.mark.asyncio
async def test_wechat_runtime_populates_anchor_detail_page() -> None:
    event = SimpleNamespace(
        account_id="40",
        session_id="50",
        occurred_at=T0,
    )
    account = SimpleNamespace(creator_id="30")
    profile = SimpleNamespace(display_name="主播")
    uow = _UoW()
    uow.live = SimpleNamespace(get_event=AsyncMock(return_value=event))
    uow.creators = SimpleNamespace(
        get_account=AsyncMock(return_value=account),
        get_profile=AsyncMock(return_value=profile),
    )
    runtime = WeChatNotificationRuntime(
        uow_factory=lambda: uow,  # type: ignore[arg-type]
        session_factory=lambda: None,  # type: ignore[arg-type]
        provider=_Provider(),
        template_id="tpl",
    )
    claimed = SimpleNamespace(
        key=SimpleNamespace(live_event_id="event-9"),
        account_id="40",
        session_id="50",
    )

    message = await runtime._build_message(claimed, openid="openid")

    assert message is not None
    assert message.page == "pages/detail/index?id=30"


def test_public_history_reads_formal_delivery_without_legacy_job_join() -> None:
    router = (ROOT / "api" / "routers" / "notifications.py").read_text(
        encoding="utf-8"
    )
    repository = (
        ROOT
        / "stage_letter"
        / "infrastructure"
        / "db"
        / "repositories"
        / "notification.py"
    ).read_text(encoding="utf-8")
    assert "NotificationJob" not in router
    assert ".offset(cursor)" not in router
    assert "list_history_for_user" in repository
    assert "NotificationDeliveryModel.id.desc()" in repository


def test_anchor_detail_has_formal_creator_fallback() -> None:
    router = (ROOT / "api" / "routers" / "anchors.py").read_text(encoding="utf-8")
    assert "_get_formal_creator_detail" in router
    assert 'last_status="LIVE" if current is not None else "UNKNOWN"' in router


def test_miniapp_history_row_navigates_only_to_detail_contract() -> None:
    page = (ROOT / "miniapp" / "pages" / "profile" / "index.js").read_text(
        encoding="utf-8"
    )
    markup = (ROOT / "miniapp" / "pages" / "profile" / "index.wxml").read_text(
        encoding="utf-8"
    )
    assert "pages/detail/index?id=" in page
    assert 'bindtap="onHistoryTap"' in markup
    assert "h.miniapp_path" in page


def test_history_index_adds_no_new_canonical_entity() -> None:
    assert "notification_history" not in Base.metadata.tables
    migration = (
        ROOT
        / "migrations"
        / "versions"
        / "e34d7a2c1b50_gate34_notification_history_index.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "e34d7a2c1b50"' in migration
    assert '"idx_g34_delivery_user_history"' in migration
    assert '["user_id", "id"]' in migration
