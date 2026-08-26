"""D3 orchestration for private, Creator-level streamer metadata."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.personal_streamer_profile import (
    PersonalStreamerProfile,
    PersonalStreamerProfileView,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_PATCH_FIELDS = {"user_alias", "note", "group", "user_tags", "reference_schedule"}


class PersonalStreamerProfileApplicationService:
    """Keep user authorship isolated from Creator and platform facts."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, *, openid: str, creator_id: str) -> PersonalStreamerProfileView:
        self._validate_openid(openid)
        self._validate_identity(creator_id, "creator_id")
        async with self._uow_factory() as uow:
            user_id = await uow.personal_profiles.get_user_id_by_openid(openid)
            if user_id is None:
                raise ApplicationNotFoundError("user not found")
            facts = await uow.personal_profiles.get_creator_facts(creator_id)
            if facts is None:
                raise ApplicationNotFoundError(f"creator {creator_id!r} not found")
            if not await uow.personal_profiles.has_active_follow(user_id, creator_id):
                raise ApplicationNotFoundError("personal profile requires an active follow")
            profile = await uow.personal_profiles.get_profile(user_id, creator_id)
        return PersonalStreamerProfileView(platform_facts=facts, user_profile=profile)

    async def patch(
        self,
        *,
        openid: str,
        creator_id: str,
        changes: Mapping[str, object],
    ) -> PersonalStreamerProfileView:
        self._validate_openid(openid)
        self._validate_identity(creator_id, "creator_id")
        unknown = set(changes) - _PATCH_FIELDS
        if unknown:
            raise ValueError(f"unsupported personal profile fields: {sorted(unknown)}")
        if not changes:
            return await self.get(openid=openid, creator_id=creator_id)

        async with self._uow_factory() as uow:
            user_id = await uow.personal_profiles.get_user_id_by_openid(openid)
            if user_id is None:
                raise ApplicationNotFoundError("user not found")
            facts = await uow.personal_profiles.get_creator_facts(creator_id)
            if facts is None:
                raise ApplicationNotFoundError(f"creator {creator_id!r} not found")
            if not await uow.personal_profiles.has_active_follow(user_id, creator_id):
                raise ApplicationNotFoundError("personal profile requires an active follow")
            current = await uow.personal_profiles.get_profile(user_id, creator_id)
            profile = self._apply_changes(user_id, creator_id, current, changes)
            await uow.personal_profiles.save_profile(profile)
            await uow.commit()
        return PersonalStreamerProfileView(platform_facts=facts, user_profile=profile)

    @classmethod
    def _apply_changes(
        cls,
        user_id: str,
        creator_id: str,
        current: PersonalStreamerProfile | None,
        changes: Mapping[str, object],
    ) -> PersonalStreamerProfile:
        values: dict[str, object] = {
            "user_alias": None if current is None else current.user_alias,
            "note": None if current is None else current.note,
            "group_name": None if current is None else current.group_name,
            "user_tags": () if current is None else current.user_tags,
            "reference_schedule": None if current is None else current.reference_schedule,
        }
        if "user_alias" in changes:
            values["user_alias"] = cls._optional_text(changes["user_alias"], "user_alias", 128)
        if "note" in changes:
            values["note"] = cls._optional_text(changes["note"], "note", 2000)
        if "group" in changes:
            values["group_name"] = cls._optional_text(changes["group"], "group", 64)
        if "user_tags" in changes:
            values["user_tags"] = cls._tags(changes["user_tags"])
        if "reference_schedule" in changes:
            values["reference_schedule"] = cls._reference_schedule(changes["reference_schedule"])
        return PersonalStreamerProfile(
            user_id=user_id, creator_id=creator_id,
            user_alias=values["user_alias"],  # type: ignore[arg-type]
            note=values["note"],  # type: ignore[arg-type]
            group_name=values["group_name"],  # type: ignore[arg-type]
            user_tags=values["user_tags"],  # type: ignore[arg-type]
            reference_schedule=values["reference_schedule"],  # type: ignore[arg-type]
        )

    @staticmethod
    def _validate_identity(value: str, field: str) -> None:
        if not value.isdigit() or int(value) < 1:
            raise ValueError(f"{field} must be a positive persistence id")

    @staticmethod
    def _validate_openid(value: str) -> None:
        if not value.strip():
            raise ValueError("openid is required")

    @staticmethod
    def _optional_text(value: object, field: str, maximum: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters")
        return normalized

    @classmethod
    def _tags(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ValueError("user_tags must be a list or null")
        if len(value) > 20:
            raise ValueError("user_tags must contain at most 20 tags")
        normalized: list[str] = []
        for tag in value:
            tag_text = cls._optional_text(tag, "user_tags[]", 32)
            if tag_text and tag_text not in normalized:
                normalized.append(tag_text)
        return tuple(normalized)

    @staticmethod
    def _reference_schedule(value: object) -> dict | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("reference_schedule must be an object or null")
        allowed = {"timezone", "days_of_week", "start_time", "end_time"}
        if set(value) - allowed:
            raise ValueError("reference_schedule contains unsupported fields")
        timezone = value.get("timezone", "Asia/Shanghai")
        if timezone != "Asia/Shanghai":
            raise ValueError("reference_schedule.timezone must be Asia/Shanghai")
        days = value.get("days_of_week", [])
        if not isinstance(days, list) or any(type(day) is not int or day < 0 or day > 6 for day in days):
            raise ValueError("reference_schedule.days_of_week must contain integers 0 through 6")
        for key in ("start_time", "end_time"):
            time_value = value.get(key)
            if time_value is not None and (not isinstance(time_value, str) or not _TIME.fullmatch(time_value)):
                raise ValueError(f"reference_schedule.{key} must use HH:MM")
        return {
            "timezone": "Asia/Shanghai",
            "days_of_week": sorted(set(days)),
            "start_time": value.get("start_time"),
            "end_time": value.get("end_time"),
        }
