"""D3 endpoints for private Creator-level streamer profiles."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from api.composition import ApiServiceBundle
from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.domain.personal_streamer_profile import PersonalStreamerProfileView

router = APIRouter()


class ReferenceScheduleResponse(BaseModel):
    timezone: str
    days_of_week: list[int]
    start_time: str | None = None
    end_time: str | None = None


class UserOwnedProfileResponse(BaseModel):
    user_alias: str | None = None
    note: str | None = None
    group: str | None = None
    user_tags: list[str] = Field(default_factory=list)
    reference_schedule: ReferenceScheduleResponse | None = None


class PlatformAccountFactResponse(BaseModel):
    account_id: str
    platform: str
    platform_user_id: str
    canonical_url: str | None = None
    enabled: bool


class CreatorPlatformFactsResponse(BaseModel):
    creator_id: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    platform_accounts: list[PlatformAccountFactResponse]


class PersonalStreamerProfileResponse(BaseModel):
    platform_facts: CreatorPlatformFactsResponse
    user_owned_profile: UserOwnedProfileResponse | None = None


class PersonalStreamerProfilePatch(BaseModel):
    """Only explicitly supplied fields change; null clears an optional field."""

    model_config = ConfigDict(extra="forbid")

    openid: str
    user_alias: str | None = None
    note: str | None = None
    group: str | None = None
    user_tags: list[str] | None = None
    reference_schedule: dict[str, Any] | None = None


def _response(view: PersonalStreamerProfileView) -> PersonalStreamerProfileResponse:
    facts = view.platform_facts
    profile = view.user_profile
    return PersonalStreamerProfileResponse(
        platform_facts=CreatorPlatformFactsResponse(
            creator_id=facts.creator_id, display_name=facts.display_name,
            avatar_url=facts.avatar_url, bio=facts.bio,
            platform_accounts=[PlatformAccountFactResponse(
                account_id=account.account_id, platform=account.platform,
                platform_user_id=account.platform_user_id,
                canonical_url=account.canonical_url, enabled=account.enabled,
            ) for account in facts.platform_accounts],
        ),
        user_owned_profile=None if profile is None else UserOwnedProfileResponse(
            user_alias=profile.user_alias, note=profile.note, group=profile.group_name,
            user_tags=list(profile.user_tags), reference_schedule=profile.reference_schedule,
        ),
    )


@router.get(
    "/creators/{creator_id}/personal-profile",
    response_model=PersonalStreamerProfileResponse,
)
async def get_personal_streamer_profile(
    request: Request, creator_id: int, openid: str,
) -> PersonalStreamerProfileResponse:
    services: ApiServiceBundle = request.app.state.stage_letter_services
    try:
        view = await services.personal_streamer_profiles.get(
            openid=openid, creator_id=str(creator_id)
        )
    except (ApplicationNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="个人主播档案不可用") from exc
    return _response(view)


@router.patch(
    "/creators/{creator_id}/personal-profile",
    response_model=PersonalStreamerProfileResponse,
)
async def patch_personal_streamer_profile(
    request: Request, creator_id: int, body: PersonalStreamerProfilePatch,
) -> PersonalStreamerProfileResponse:
    changes = {
        field: getattr(body, field)
        for field in ("user_alias", "note", "group", "user_tags", "reference_schedule")
        if field in body.model_fields_set
    }
    services: ApiServiceBundle = request.app.state.stage_letter_services
    try:
        view = await services.personal_streamer_profiles.patch(
            openid=body.openid, creator_id=str(creator_id), changes=changes
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="个人主播档案不可用") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(view)
