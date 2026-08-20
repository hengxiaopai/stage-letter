"""Gate 2 detection composition root.

It reuses Gate 1's formal provider ingress and scheduler while replacing the
all-enabled target source with Gate 2.1 due-aware selection.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.monitoring_probe import MonitoringProbeApplicationService
from stage_letter.detection.due import DetectionCadencePolicy
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.detection import SQLAlchemyDetectionScheduleRepository
from stage_letter.infrastructure.platforms import AdapterRegistry, build_formal_adapter_registry
from workers.monitoring import MonitoringScheduler, MonitoringSchedulerPolicy

SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class DetectionSchedulingBundle:
    due_targets: DueMonitoringTargetApplicationService
    adapter_registry: AdapterRegistry
    monitoring_probe: MonitoringProbeApplicationService
    monitoring_scheduler: MonitoringScheduler


def build_detection_scheduling(
    session_factory: SessionFactory,
    *,
    douyin_cookie: str | None = None,
    cadence_policy: DetectionCadencePolicy | None = None,
    scheduler_policy: MonitoringSchedulerPolicy | None = None,
) -> DetectionSchedulingBundle:
    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    schedule_repository = SQLAlchemyDetectionScheduleRepository(session_factory)
    due_targets = DueMonitoringTargetApplicationService(
        schedule_repository,
        cadence=cadence_policy,
    )
    adapter_registry = build_formal_adapter_registry(douyin_cookie=douyin_cookie)
    monitoring_probe = MonitoringProbeApplicationService(uow_factory, adapter_registry.get)
    monitoring_scheduler = MonitoringScheduler(
        due_targets,  # same accepted list_targets paging contract
        monitoring_probe,
        policy=scheduler_policy,
    )
    return DetectionSchedulingBundle(
        due_targets=due_targets,
        adapter_registry=adapter_registry,
        monitoring_probe=monitoring_probe,
        monitoring_scheduler=monitoring_scheduler,
    )
