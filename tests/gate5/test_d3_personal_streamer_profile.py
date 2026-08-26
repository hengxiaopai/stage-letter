from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.services.personal_streamer_profile import (
    PersonalStreamerProfileApplicationService,
)
from stage_letter.domain.personal_streamer_profile import CreatorPlatformFacts
from stage_letter.domain.creators import PlatformAccount


class _UoW:
    def __init__(self) -> None:
        facts = CreatorPlatformFacts(
            creator_id="30", display_name="平台昵称", avatar_url="https://avatar", bio="平台简介",
            platform_accounts=(PlatformAccount("40", "30", "douyin", "dy-30"),),
        )
        self.rows = {}
        self.personal_profiles = SimpleNamespace(
            get_user_id_by_openid=AsyncMock(side_effect=lambda openid: {"user-a": "10", "user-b": "20"}.get(openid)),
            get_creator_facts=AsyncMock(return_value=facts),
            has_active_follow=AsyncMock(return_value=True),
            get_profile=AsyncMock(side_effect=lambda user_id, creator_id: self.rows.get((user_id, creator_id))),
            save_profile=AsyncMock(side_effect=self._save),
        )
        self.commit = AsyncMock()

    async def _save(self, profile) -> None:
        self.rows[(profile.user_id, profile.creator_id)] = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_personal_profile_isolated_by_user_and_platform_name_cannot_overwrite_alias() -> None:
    uow = _UoW()
    service = PersonalStreamerProfileApplicationService(lambda: uow)  # type: ignore[arg-type]
    patched = await service.patch(
        openid="user-a", creator_id="30",
        changes={
            "user_alias": "我的大司马", "note": "只看晚场", "group": "电竞",
            "user_tags": ["常看", "常看", "回放"],
            "reference_schedule": {"days_of_week": [5, 1, 5], "start_time": "20:00", "end_time": "23:00"},
        },
    )
    assert patched.platform_facts.display_name == "平台昵称"
    assert patched.user_profile is not None
    assert patched.user_profile.user_alias == "我的大司马"
    assert patched.user_profile.user_tags == ("常看", "回放")

    other = await service.get(openid="user-b", creator_id="30")
    assert other.platform_facts.display_name == "平台昵称"
    assert other.user_profile is None

    # A later platform nickname refresh remains in the platform layer only.
    uow.personal_profiles.get_creator_facts.return_value = CreatorPlatformFacts(
        creator_id="30", display_name="平台新昵称", avatar_url=None, bio=None,
        platform_accounts=(PlatformAccount("40", "30", "douyin", "dy-30"),),
    )
    reread = await service.get(openid="user-a", creator_id="30")
    assert reread.platform_facts.display_name == "平台新昵称"
    assert reread.user_profile is not None
    assert reread.user_profile.user_alias == "我的大司马"


@pytest.mark.asyncio
async def test_repeated_patch_is_idempotent_and_requires_a_current_follow() -> None:
    uow = _UoW()
    service = PersonalStreamerProfileApplicationService(lambda: uow)  # type: ignore[arg-type]
    changes = {"user_alias": "晚间档", "user_tags": ["游戏"], "reference_schedule": None}
    first = await service.patch(openid="user-a", creator_id="30", changes=changes)
    second = await service.patch(openid="user-a", creator_id="30", changes=changes)
    assert first.user_profile == second.user_profile
    assert uow.personal_profiles.save_profile.await_count == 2
    assert uow.commit.await_count == 2

    uow.personal_profiles.has_active_follow.return_value = False
    with pytest.raises(ApplicationNotFoundError, match="active follow"):
        await service.get(openid="user-a", creator_id="30")


def test_profile_contract_stays_creator_scoped_and_never_owns_live_or_reminder_truth() -> None:
    source = ("stage_letter/application/services/personal_streamer_profile.py")
    text = open(source, encoding="utf-8").read()
    assert "platform_account_id" not in text
    assert "notification" not in text.lower()
    assert "LIVE" not in text
    assert "OFFLINE" not in text
