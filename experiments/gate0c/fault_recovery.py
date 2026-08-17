#!/usr/bin/env python3
"""Gate 0C-3 deterministic fault/recovery scenario harness.

This composes the canonical Gate 0C HealthTracker and poll policy. It does not
perform provider HTTP calls and does not own creator LiveSession state. The
separate real StreamGet soak harness supplies provider evidence later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from platform_health import (
    CanonicalStatus,
    FailureKind,
    HealthConfig,
    HealthState,
    HealthTracker,
    ProbeSample,
)
from poll_policy import PollContext, PollDecision, PollPolicyConfig, decide_poll


@dataclass(frozen=True)
class ScenarioStep:
    step_id: str
    started_at: datetime
    status: CanonicalStatus
    latency_ms: int = 300
    failure_kind: FailureKind | None = None

    def to_probe_sample(self) -> ProbeSample:
        return ProbeSample(
            sample_id=self.step_id,
            started_at=self.started_at,
            completed_at=self.started_at + timedelta(milliseconds=self.latency_ms),
            status=self.status,
            latency_ms=self.latency_ms,
            failure_kind=self.failure_kind,
            source="gate0c-fault-scenario",
        )


@dataclass(frozen=True)
class ScenarioRecord:
    step_id: str
    canonical_status: CanonicalStatus
    failure_kind: FailureKind | None
    accepted: bool
    duplicate: bool
    stale: bool
    health_before: HealthState
    health_after: HealthState
    consecutive_failures: int
    poll_decision: PollDecision


def run_scenario(
    steps: Iterable[ScenarioStep],
    *,
    health_config: HealthConfig | None = None,
    poll_config: PollPolicyConfig | None = None,
    jitter_unit: float = 0.0,
) -> tuple[ScenarioRecord, ...]:
    """Execute a deterministic health + scheduler fault sequence."""

    tracker = HealthTracker(config=health_config)
    records: list[ScenarioRecord] = []

    for step in steps:
        sample = step.to_probe_sample()
        result = tracker.process(sample)
        snapshot = tracker.snapshot()
        poll = decide_poll(
            PollContext(
                health_state=snapshot.state,
                failure_kind=step.failure_kind,
                consecutive_failures=snapshot.consecutive_failures,
                jitter_unit=jitter_unit,
            ),
            poll_config,
        )
        records.append(
            ScenarioRecord(
                step_id=step.step_id,
                canonical_status=result.canonical_status,
                failure_kind=result.failure_kind,
                accepted=result.accepted,
                duplicate=result.duplicate,
                stale=result.stale,
                health_before=result.previous_state,
                health_after=result.current_state,
                consecutive_failures=snapshot.consecutive_failures,
                poll_decision=poll,
            )
        )

    return tuple(records)
