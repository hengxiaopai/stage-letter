"""Gate 2 detection composition root.

Construction is I/O-free. Gate 2.1 due selection, Gate 2.2 runtime coordination,
Gate 1.4 durable provider ingress, Gate 2.3 telemetry, Gate 2.4 health state, and
Gate 2.5 durable cross-worker leases are wired without reviving the legacy worker.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.application.services.detection_health import (
    DetectionHealthAdministrationApplicationService,
    HealthAwareDetectionTelemetryApplicationService,
)
from stage_letter.application.services.detection_lease import DetectionLeaseApplicationService
from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.application.services.monitoring_probe import MonitoringProbeApplicationService
from stage_letter.detection.due import DetectionCadencePolicy
from stage_letter.detection.health import CircuitBreakerPolicy
from stage_letter.detection.lease import DetectionLeasePolicy
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.detection import (
    SQLAlchemyDetectionHealthRepository,
    SQLAlchemyDetectionLeaseRepository,
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
    telemetry: HealthAwareDetectionTelemetryApplicationService
    health_administration: DetectionHealthAdministrationApplicationService
    leases: DetectionLeaseApplicationService
    worker_token: str
    coordinator: DetectionRuntimeCoordinator
    runtime: DetectionCycleRuntime


def build_detection_scheduling(
    session_factory: SessionFactory,
    *,
    douyin_cookie: str | None = None,
    cadence_policy: DetectionCadencePolicy | None = None,
    circuit_breaker_policy: CircuitBreakerPolicy | None = None,
    scheduler_policy: MonitoringSchedulerPolicy | None = None,
) -> DetectionSchedulingBundle:
    def uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    schedule_repository = SQLAlchemyDetectionScheduleRepository(session_factory)
    due_targets = DueMonitoringTargetApplicationService(
        schedule_repository,
        cadence=cadence_policy,
        circuit_breaker=circuit_breaker_policy,
    )
    adapter_registry = build_formal_adapter_registry(douyin_cookie=douyin_cookie)
    monitoring_probe = MonitoringProbeApplicationService(uow_factory, adapter_registry.get)
    monitoring_scheduler = MonitoringScheduler(
        due_targets,
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
    circuit_breaker_policy: CircuitBreakerPolicy | None = None,
    lease_policy: DetectionLeasePolicy | None = None,
    worker_token: str | None = None,
    runtime_policy: PlatformRuntimePolicy | None = None,
    platform_runtime_policies: dict[str, PlatformRuntimePolicy] | None = None,
    page_size: int = 100,
) -> DetectionRuntimeBundle:
    """Build the formal Gate 2.5 runtime without opening DB/provider I/O."""

    policy = circuit_breaker_policy or CircuitBreakerPolicy()
    scheduling = build_detection_scheduling(
        session_factory,
        douyin_cookie=douyin_cookie,
        cadence_policy=cadence_policy,
        circuit_breaker_policy=policy,
    )
    base_telemetry = DetectionTelemetryApplicationService(
        SQLAlchemyDetectionTelemetryRepository(session_factory)
    )
    health_repository = SQLAlchemyDetectionHealthRepository(session_factory)
    telemetry = HealthAwareDetectionTelemetryApplicationService(
        base_telemetry,
        health_repository,
        policy=policy,
    )
    health_administration = DetectionHealthAdministrationApplicationService(
        health_repository
    )
    leases = DetectionLeaseApplicationService(
        SQLAlchemyDetectionLeaseRepository(session_factory),
        policy=lease_policy,
    )
    token = worker_token or uuid.uuid4().hex
    coordinator = DetectionRuntimeCoordinator(
        default_policy=runtime_policy,
        platform_policies=platform_runtime_policies,
    )
    runtime = DetectionCycleRuntime(
        scheduling.due_targets,
        scheduling.monitoring_probe,
        coordinator,
        telemetry=telemetry,
        leases=leases,
        owner_token=token,
        page_size=page_size,
    )
    return DetectionRuntimeBundle(
        scheduling=scheduling,
        telemetry=telemetry,
        health_administration=health_administration,
        leases=leases,
        worker_token=token,
        coordinator=coordinator,
        runtime=runtime,
    )
