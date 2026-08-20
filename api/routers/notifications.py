"""Notification grant intake and legacy history routes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.composition import ApiServiceBundle
from core.config import settings
from core.db import get_db
from core.models import (
    Anchor,
    LiveSession,
    NotificationDelivery,
    NotificationJob,
    User,
)
from stage_letter.application.services import GrantIntakeConflictError
from stage_letter.domain.grant_intake import GrantIntakeDecision

router = APIRouter()

class GrantResponse(BaseModel):
    template_id: str
    granted_count: int
    consumed_count: int
    available: int
    last_granted_at: datetime | None = None
    last_send_at: datetime | None = None
    last_send_error: str | None = None
    ledger_drift_detected: bool = False


class GrantIntakeItem(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    decision: GrantIntakeDecision


class RequestGrantRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    results: list[GrantIntakeItem] = Field(min_length=1, max_length=5)


class GrantIntakeItemResponse(BaseModel):
    template_id: str
    decision: GrantIntakeDecision
    recorded: bool
    granted_count: int
    consumed_count: int
    available: int


class RequestGrantResponse(BaseModel):
    request_id: str
    items: list[GrantIntakeItemResponse]
    received_at: datetime


async def _get_or_create_user(db: AsyncSession, openid: str) -> User:
    r = await db.execute(select(User).where(User.openid == openid))
    user = r.scalar_one_or_none()
    if user is None:
        user = User(openid=openid)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _get_existing_user(db: AsyncSession, openid: str) -> User:
    user = (
        await db.execute(select(User).where(User.openid == openid))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user must login before grant intake")
    return user


def _configured_template_id() -> str:
    template_id = settings.wx_template_live_start.strip()
    if not template_id:
        raise HTTPException(status_code=503, detail="WeChat template is not configured")
    return template_id


def _grant_response(
    template_id: str,
    granted: int,
    consumed: int,
    *,
    last_granted_at: datetime | None = None,
    last_send_at: datetime | None = None,
    last_send_error: str | None = None,
) -> GrantResponse:
    return GrantResponse(
        template_id=template_id,
        granted_count=granted,
        consumed_count=consumed,
        available=max(0, granted - consumed),
        last_granted_at=last_granted_at,
        last_send_at=last_send_at,
        last_send_error=last_send_error,
        ledger_drift_detected=consumed > granted,
    )


@router.get("/notifications/grants", response_model=GrantResponse)
async def get_grants(
    request: Request,
    openid: str = Query(..., description="微信 openid(dev 阶段直接传,生产换 token)"),
    template_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> GrantResponse:
    resolved_template = template_id or _configured_template_id()
    if resolved_template != _configured_template_id():
        raise HTTPException(status_code=422, detail="template is not registered for grant intake")
    user = await _get_existing_user(db, openid)
    services: ApiServiceBundle = request.app.state.stage_letter_services
    ledger = await services.grants.get_ledger(str(user.id), resolved_template)
    return _grant_response(
        resolved_template,
        ledger.granted_count,
        ledger.consumed_count,
        last_granted_at=ledger.last_granted_at,
        last_send_at=ledger.last_send_at,
        last_send_error=ledger.last_send_error,
    )


@router.post("/notifications/request-grant", response_model=RequestGrantResponse)
async def request_grant(
    req: RequestGrantRequest,
    request: Request,
    openid: str = Query(..., description="微信 openid"),
    db: AsyncSession = Depends(get_db),
) -> RequestGrantResponse:
    configured_template = _configured_template_id()
    if any(item.template_id != configured_template for item in req.results):
        raise HTTPException(status_code=422, detail="template is not registered for grant intake")
    user = await _get_existing_user(db, openid)
    now = datetime.now(timezone.utc)
    services: ApiServiceBundle = request.app.state.stage_letter_services
    try:
        results = await services.grants.record_intake(
            user_id=str(user.id),
            request_id=req.request_id,
            results=tuple((item.template_id, item.decision) for item in req.results),
            received_at=now,
        )
    except GrantIntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RequestGrantResponse(
        request_id=req.request_id,
        received_at=now,
        items=[
            GrantIntakeItemResponse(
                template_id=result.intake.template_id,
                decision=result.intake.decision,
                recorded=result.created,
                granted_count=result.ledger.granted_count,
                consumed_count=result.ledger.consumed_count,
                available=result.ledger.available,
            )
            for result in results
        ],
    )


class HistoryItem(BaseModel):
    id: int
    anchor_id: int
    display_name: str | None = None
    platform: str | None = None
    live_session_id: int | None = None
    started_at: datetime | None = None
    channel: str | None = None
    state: str
    error_code: str | None = None
    sent_at: datetime | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    next_cursor: str | None = None


@router.get("/notifications/history", response_model=HistoryResponse)
async def notification_history(
    openid: str = Query(...),
    limit: int = Query(20, ge=1, le=50),
    cursor: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    user = await _get_or_create_user(db, openid)

    rows = (
        await db.execute(
            select(NotificationDelivery, NotificationJob, LiveSession, Anchor)
            .join(NotificationJob, NotificationDelivery.notification_job_id == NotificationJob.id)
            .outerjoin(LiveSession, NotificationDelivery.live_session_id == LiveSession.id)
            .join(Anchor, NotificationJob.anchor_id == Anchor.id)
            .where(NotificationDelivery.user_id == user.id)
            .order_by(NotificationDelivery.id.desc())
            .offset(cursor)
            .limit(limit)
        )
    ).all()

    items = [
        HistoryItem(
            id=d.id,
            anchor_id=a.id,
            display_name=a.display_name,
            platform=ls.platform if ls else None,
            live_session_id=d.live_session_id,
            started_at=ls.started_at if ls else None,
            channel=d.channel,
            state=d.state,
            error_code=d.error_code,
            sent_at=d.sent_at,
        )
        for d, nj, ls, a in rows
    ]

    next_cursor = str(cursor + limit) if len(items) == limit else None
    return HistoryResponse(items=items, next_cursor=next_cursor)
