from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routers.anchors import _viewer_context_by_account
from api.routers.subscriptions import (
    ReminderPreferencePatch,
    patch_reminder_preference,
)
from core.models import User, UserSubscription
from stage_letter.infrastructure.db.models import FollowModel, NotificationPreferenceModel


ROOT = Path(__file__).resolve().parents[2]


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _ExecuteResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)


class _ViewerDb:
    def __init__(self, user, follows, preferences):
        self.user = user
        self.results = iter([follows, preferences])

    async def scalar(self, _statement):
        return self.user

    async def execute(self, _statement):
        return _ExecuteResult(next(self.results))


class _PatchDb:
    def __init__(self, scalar_results):
        self.scalar_results = iter(scalar_results)
        self.committed = False

    async def scalar(self, _statement):
        return next(self.scalar_results)

    def add(self, _value):
        pass

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        value.updated_at = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_detail_viewer_context_uses_formal_follow_and_preference() -> None:
    user = User(id=7, openid="viewer-7")
    follow = FollowModel(user_id=7, creator_id=8, platform_account_id=9)
    preference = NotificationPreferenceModel(
        user_id=7,
        platform_account_id=9,
        enabled=False,
    )
    db = _ViewerDb(user, [follow], [preference])

    context = await _viewer_context_by_account(
        db,  # type: ignore[arg-type]
        openid="viewer-7",
        account_ids=[9, 10],
    )

    assert context[9] == {"is_following": True, "reminder_enabled": False}
    assert context[10] == {"is_following": False, "reminder_enabled": None}


@pytest.mark.asyncio
async def test_patch_updates_formal_and_legacy_preference() -> None:
    user = User(id=7, openid="viewer-7")
    follow = FollowModel(user_id=7, creator_id=8, platform_account_id=9)
    preference = NotificationPreferenceModel(
        user_id=7,
        platform_account_id=9,
        enabled=True,
    )
    legacy = UserSubscription(
        user_id=7,
        anchor_id=8,
        platform_account_id=9,
        notify_enabled=True,
    )
    db = _PatchDb([user, follow, preference, legacy])

    response = await patch_reminder_preference(
        9,
        ReminderPreferencePatch(openid="viewer-7", enabled=False),
        db,  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert response.enabled is False
    assert preference.enabled is False
    assert legacy.notify_enabled is False


@pytest.mark.asyncio
async def test_patch_rejects_non_owner() -> None:
    user = User(id=7, openid="viewer-7")
    db = _PatchDb([user, None])

    with pytest.raises(HTTPException) as error:
        await patch_reminder_preference(
            9,
            ReminderPreferencePatch(openid="viewer-7", enabled=False),
            db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 404


def test_miniapp_detail_has_no_default_on_and_rolls_back_failed_write() -> None:
    detail = (ROOT / "miniapp" / "pages" / "detail" / "index.js").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "miniapp" / "services" / "subscriptions.js").read_text(
        encoding="utf-8"
    )

    assert "remindOn: true" not in detail
    assert "platform.reminder_enabled" in detail
    assert "await updateReminderPreference(" in detail
    assert "this.setData({ remindOn: previous })" in detail
    assert "method: 'PATCH'" in service
