"""Formal worker composition root for Stage Letter.

This module is the worker-side composition boundary. It wires formal application
services, the accepted four-platform AdapterRegistry, monitoring, state replay,
and idempotent observation consumption without performing provider or database
I/O during construction.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services import (
    CreatorApplicationService,
    FollowApplicationService,
    LiveObservationApplicationService,
    LiveObservationConsumptionApplicationService,
    LiveTransitionPersistenceApplicationService,
    MonitoringProbeApplicationService,
    MonitoringTargetApplicationService,
    StateReconstructionApplicationService,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.platforms import (
    AdapterRegistry,
    build_formal_adapter_registry,
)
from workers.monitoring import MonitoringScheduler, MonitoringSchedulerPolicy


SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class WorkerServiceBundle:
    creators: CreatorApplicationService
    follows: FollowApplicationService
    live_observations: LiveObservationApplicationService
    monitoring_targets: MonitoringTargetApplicationService
    adapter_registry: AdapterRegistry
    monitoring_probe: MonitoringProbeApplicationService
    monitoring_scheduler: MonitoringScheduler
    state_reconstruction: StateReconstructionApplicationService
    live_transitions: LiveTransitionPersistenceApplicationService
    live_observation_consumer: LiveObservationConsumptionApplicationService


def build_worker_services(
    session_factory: SessionFactory,
    *,
    douyin_cookie: str | None = None,
    scheduler_policy: MonitoringSchedulerPolicy | None = None,
) -> WorkerServiceBundle:
    """Build the formal four-platform worker runtime without opening I/O.

    SQLAlchemy UnitOfWork instances are created lazily when a use-case enters a
    transaction. Provider requests happen only inside adapter operations. State
    reconstruction/consumption likewise performs no work until explicitly called.
    """

    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    creators = CreatorApplicationService(uow_factory)
    follows = FollowApplicationService(uow_factory)
    live_observations = LiveObservationApplicationService(uow_factory)
    monitoring_targets = MonitoringTargetApplicationService(uow_factory)

    adapter_registry = build_formal_adapter_registry(douyin_cookie=douyin_cookie)
    monitoring_probe = MonitoringProbeApplicationService(
        uow_factory,
        adapter_registry.get,
    )
    monitoring_scheduler = MonitoringScheduler(
        monitoring_targets,
        monitoring_probe,
        policy=scheduler_policy,
    )

    state_reconstruction = StateReconstructionApplicationService(uow_factory)
    live_transitions = LiveTransitionPersistenceApplicationService(uow_factory)
    live_observation_consumer = LiveObservationConsumptionApplicationService(
        state_reconstruction,
        live_transitions,
    )

    return WorkerServiceBundle(
        creators=creators,
        follows=follows,
        live_observations=live_observations,
        monitoring_targets=monitoring_targets,
        adapter_registry=adapter_registry,
        monitoring_probe=monitoring_probe,
        monitoring_scheduler=monitoring_scheduler,
        state_reconstruction=state_reconstruction,
        live_transitions=live_transitions,
        live_observation_consumer=live_observation_consumer,
    )
