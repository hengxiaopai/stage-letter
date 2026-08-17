#!/usr/bin/env python3
"""Stage Letter Gate 0C-1 — provider health state engine.

This module is intentionally provider-agnostic and has no HTTP, database,
queue, scheduler, or Gate 0B dependency. It models only operational health of
one polling source/route.

Critical boundary:
- provider health is NOT creator live state;
- a failed probe may contribute to DEGRADED/UNAVAILABLE health, but it must not
  be translated into creator OFFLINE;
- only the adapter/state pipeline may decide canonical LIVE/OFFLINE/UNKNOWN.

Gate defaults are acceptance-test parameters, not frozen production tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class HealthState(str, Enum):
    UNPROVEN = "UNPROVEN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ProbeOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class FailureClass(str, Enum):
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_BLOCK = "AUTH_BLOCK"
    CHALLENGE = "CHALLENGE"
    TRANSPORT = "TRANSPORT"
    PARSE_SCHEMA = "PARSE_SCHEMA"
    UPSTREAM = "UPSTREAM"
    AMBIGUOUS = "AMBIGUOUS"
    OTHER = "OTHER"


@dataclass(frozen=True)
class HealthPolicy:
    degraded_after_failures: int = 2
    unavailable_after_failures: int = 5
    recover_after_successes: int = 2

    def __post_init__(self) -> None:
        if self.degraded_after_failures < 1:
            raise ValueError("degraded_after_failures must be >= 1")
        if self.unavailable_after_failures < self.degraded_after_failures:
            raise ValueError(
                "unavailable_after_failures must be >= degraded_after_failures"
            )
        if self.recover_after_successes < 1:
            raise ValueError("recover_after_successes must be >= 1")


@dataclass(frozen=True)
class HealthSample:
    sample_id: str
    outcome: ProbeOutcome
    completed_at: datetime
    latency_ms: int | None = None
    failure_class: FailureClass | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must not be empty")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if self.outcome is ProbeOutcome.SUCCESS:
            if self.failure_class is not None or self.error_type is not None:
                raise ValueError("successful sample cannot carry failure metadata")
        else:
            if self.failure_class is None:
                raise ValueError("failed sample requires failure_class")


@dataclass(frozen=True)
class HealthSnapshot:
    state: HealthState
    consecutive_successes: int
    consecutive_failures: int
    total_samples: int
    success_count: int
    failure_count: int
    last_sample_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_class: FailureClass | None
    last_error_type: str | None
    last_latency_ms: int | None
    seen_sample_ids: frozenset[str]


@dataclass(frozen=True)
class HealthProcessResult:
    accepted: bool
    duplicate: bool
    previous_state: HealthState
    current_state: HealthState
    state_changed: bool


class HealthEngine:
    """Pure health engine for one provider route / polling source."""

    def __init__(self, policy: HealthPolicy | None = None) -> None:
        self.policy = policy or HealthPolicy()
        self.state = HealthState.UNPROVEN
        self.consecutive_successes = 0
        self.consecutive_failures = 0
        self.total_samples = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_sample_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_failure_at: datetime | None = None
        self.last_failure_class: FailureClass | None = None
        self.last_error_type: str | None = None
        self.last_latency_ms: int | None = None
        self._seen_sample_ids: set[str] = set()

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(
            state=self.state,
            consecutive_successes=self.consecutive_successes,
            consecutive_failures=self.consecutive_failures,
            total_samples=self.total_samples,
            success_count=self.success_count,
            failure_count=self.failure_count,
            last_sample_at=self.last_sample_at,
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_failure_class=self.last_failure_class,
            last_error_type=self.last_error_type,
            last_latency_ms=self.last_latency_ms,
            seen_sample_ids=frozenset(self._seen_sample_ids),
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: HealthSnapshot,
        policy: HealthPolicy | None = None,
    ) -> "HealthEngine":
        engine = cls(policy=policy)
        engine.state = snapshot.state
        engine.consecutive_successes = snapshot.consecutive_successes
        engine.consecutive_failures = snapshot.consecutive_failures
        engine.total_samples = snapshot.total_samples
        engine.success_count = snapshot.success_count
        engine.failure_count = snapshot.failure_count
        engine.last_sample_at = snapshot.last_sample_at
        engine.last_success_at = snapshot.last_success_at
        engine.last_failure_at = snapshot.last_failure_at
        engine.last_failure_class = snapshot.last_failure_class
        engine.last_error_type = snapshot.last_error_type
        engine.last_latency_ms = snapshot.last_latency_ms
        engine._seen_sample_ids = set(snapshot.seen_sample_ids)
        engine._assert_invariants()
        return engine

    def process(self, sample: HealthSample) -> HealthProcessResult:
        previous_state = self.state

        if sample.sample_id in self._seen_sample_ids:
            return HealthProcessResult(
                accepted=False,
                duplicate=True,
                previous_state=previous_state,
                current_state=self.state,
                state_changed=False,
            )

        self._seen_sample_ids.add(sample.sample_id)
        self.total_samples += 1
        self.last_sample_at = sample.completed_at
        self.last_latency_ms = sample.latency_ms

        if sample.outcome is ProbeOutcome.SUCCESS:
            self._process_success(sample)
        else:
            self._process_failure(sample)

        self._assert_invariants()
        return HealthProcessResult(
            accepted=True,
            duplicate=False,
            previous_state=previous_state,
            current_state=self.state,
            state_changed=self.state is not previous_state,
        )

    def _process_success(self, sample: HealthSample) -> None:
        self.success_count += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_at = sample.completed_at

        if self.state is HealthState.UNPROVEN:
            self.state = HealthState.HEALTHY
            return

        if self.state in (HealthState.DEGRADED, HealthState.UNAVAILABLE):
            # Do not recover on a single lucky response. Health remains at the
            # existing severity until the configured success streak is proven.
            if self.consecutive_successes >= self.policy.recover_after_successes:
                self.state = HealthState.HEALTHY

    def _process_failure(self, sample: HealthSample) -> None:
        self.failure_count += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_at = sample.completed_at
        self.last_failure_class = sample.failure_class
        self.last_error_type = sample.error_type

        if self.consecutive_failures >= self.policy.unavailable_after_failures:
            self.state = HealthState.UNAVAILABLE
            return

        if self.consecutive_failures >= self.policy.degraded_after_failures:
            # Failure must never improve an already UNAVAILABLE route.
            if self.state is not HealthState.UNAVAILABLE:
                self.state = HealthState.DEGRADED

    def _assert_invariants(self) -> None:
        if self.consecutive_successes < 0 or self.consecutive_failures < 0:
            raise AssertionError("health streaks must be non-negative")
        if self.consecutive_successes and self.consecutive_failures:
            raise AssertionError("success and failure streaks cannot both be non-zero")
        if self.total_samples != self.success_count + self.failure_count:
            raise AssertionError("health sample counters are inconsistent")
        if self.total_samples != len(self._seen_sample_ids):
            raise AssertionError("accepted sample count must equal unique sample ids")
        if self.success_count and self.last_success_at is None:
            raise AssertionError("success_count requires last_success_at")
        if self.failure_count and self.last_failure_at is None:
            raise AssertionError("failure_count requires last_failure_at")
