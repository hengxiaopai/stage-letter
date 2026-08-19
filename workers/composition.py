"""Formal worker composition root for Stage Letter.

The current legacy probe/notify workers are intentionally not rewritten here;
this module provides the concrete dependency seam later Gate 1 workers must use.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services import (
    CreatorApplicationService,
    FollowApplicationService,
    LiveObservationApplicationService,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class WorkerServiceBundle:
    creators: CreatorApplicationService
    follows: FollowApplicationService
    live_observations: LiveObservationApplicationService


def build_worker_services(session_factory: SessionFactory) -> WorkerServiceBundle:
    """Wire worker-side application services to the formal SQLAlchemy UoW."""

    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    return WorkerServiceBundle(
        creators=CreatorApplicationService(uow_factory),
        follows=FollowApplicationService(uow_factory),
        live_observations=LiveObservationApplicationService(uow_factory),
    )
