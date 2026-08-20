"""Gate 2 detection composition root.

Construction is I/O-free. Gate 2.1 due selection, Gate 2.2 runtime coordination,
Gate 1.4 durable provider ingress, and Gate 2.3 operational telemetry are wired
without reviving the legacy probe worker.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.application.services.monitoring_probe import MonitoringProbeApplicationService
from stage_letter.detection.due import DetectionCadencePolicy
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.detection import (
    SQLAlchemyDetectionScheduleRepository,
    SQLAlchemyDetectionTelemetryRepository,
)
from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
)
from stage_letter.infrastructure.platforms import AdapterRegistry, build_formal_adapter_registry
from workers.detection_runtime import DetectionCycleRuntime
from workers.monitoring import MonitoringScheduler, MonitoringSchedulerPolicy

SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class DetectionSchedulingBundle:
    due_targets: DueMonitoringTargetApplicationService
    adapter_registry: AdapterRegistry
    monitoring_probe: MonitoringProbeApplicationService
    monitoring_scheduler: MonitoringScheduler


@dataclass(frozen=True)
class DetectionRuntimeBundle:
    scheduling: DetectionSchedulingBundle
    telemetry: DetectionTelemetryApplicationService
    coordinator: DetectionRuntimeCoordinator
    runtime: DetectionCycleRuntime


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


def build_detection_runtime(
    session_factory: SessionFactory,
    *,
    douyin_cookie: str | None = None,
    cadence_policy: DetectionCadencePolicy | None = None,
    runtime_policy: PlatformRuntimePolicy | None = None,
    platform_runtime_policies: dict[str, PlatformRuntimePolicy] | None = None,
    page_size: int = 100,
) -> DetectionRuntimeBundle:
    """Build the formal Gate 2.3 runtime without opening DB/provider I/O."""

    scheduling = build_detection_scheduling(
        session_factory,
        douyin_cookie=douyin_cookie,
        cadence_policy=cadence_policy,
    )
    telemetry = DetectionTelemetryApplicationService(
        SQLAlchemyDetectionTelemetryRepository(session_factory)
    )
    coordinator = DetectionRuntimeCoordinator(
        default_policy=runtime_policy,
        platform_policies=platform_runtime_policies,
    )
    runtime = DetectionCycleRuntime(
        scheduling.due_targets,
        scheduling.monitoring_probe,
        coordinator,
        telemetry=telemetry,
        page_size=page_size,
    )
    return DetectionRuntimeBundle(
        scheduling=scheduling,
        telemetry=telemetry,
        coordinator=coordinator,
        runtime=runtime,
    )
