"""Formal API composition root for Stage Letter.

This outer-layer module is allowed to know both application services and their
SQLAlchemy UnitOfWork implementation. Business rules remain inside domain /
application modules; this file only wires concrete dependencies.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services import (
    CreatorApplicationService,
    FollowApplicationService,
    LiveObservationApplicationService,
    NotificationHistoryApplicationService,
    PersonalStreamerProfileApplicationService,
    SessionInsightsApplicationService,
    WeChatGrantApplicationService,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class ApiServiceBundle:
    creators: CreatorApplicationService
    follows: FollowApplicationService
    live_observations: LiveObservationApplicationService
    grants: WeChatGrantApplicationService
    notification_history: NotificationHistoryApplicationService
    session_insights: SessionInsightsApplicationService
    personal_streamer_profiles: PersonalStreamerProfileApplicationService


def build_api_services(session_factory: SessionFactory) -> ApiServiceBundle:
    """Wire formal application services to one SQLAlchemy UnitOfWork factory."""

    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    return ApiServiceBundle(
        creators=CreatorApplicationService(uow_factory),
        follows=FollowApplicationService(uow_factory),
        live_observations=LiveObservationApplicationService(uow_factory),
        grants=WeChatGrantApplicationService(uow_factory),
        notification_history=NotificationHistoryApplicationService(uow_factory),
        session_insights=SessionInsightsApplicationService(uow_factory),
        personal_streamer_profiles=PersonalStreamerProfileApplicationService(uow_factory),
    )
