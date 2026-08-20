from __future__ import annotations

from stage_letter.application.services.detection_telemetry import DetectionTelemetryApplicationService
from stage_letter.infrastructure.detection.runtime import DetectionRuntimeCoordinator
from workers.detection_composition import build_detection_runtime
from workers.detection_runtime import DetectionCycleRuntime


def test_gate23_runtime_composition_is_io_free_and_wires_telemetry() -> None:
    def forbidden_session_factory():
        raise AssertionError("composition must not open DB I/O")

    bundle = build_detection_runtime(forbidden_session_factory)  # type: ignore[arg-type]

    assert isinstance(bundle.telemetry, DetectionTelemetryApplicationService)
    assert isinstance(bundle.coordinator, DetectionRuntimeCoordinator)
    assert isinstance(bundle.runtime, DetectionCycleRuntime)
    assert bundle.runtime._telemetry is bundle.telemetry
    assert bundle.scheduling.monitoring_probe is bundle.runtime._probes
