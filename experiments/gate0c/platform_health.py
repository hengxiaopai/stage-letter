#!/usr/bin/env python3
"""Stage Letter Gate 0C — platform/provider health policy.

This module is intentionally independent from Gate 0B canonical live-state
semantics. Health may describe source quality, but it must never rewrite a
normalized LIVE/OFFLINE/UNKNOWN fact into another status.

One HealthTracker represents one monitoring scope, for example one
provider/account pair. Platform-wide health can be derived with
``aggregate_health`` without collapsing partial failures into a false global
outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable


class CanonicalStatus(str, Enum):
    LIVE = "LIVE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class HealthState(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class FailureKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    RATE_LIMIT = "RATE_LIMIT"
    PARSE = "PARSE"
    AUTH = "AUTH"
    BLOCKED = "BLOCKED"
    EMPTY = "EMPTY"
    OTHER = "OTHER"


@dataclass(frozen=True)
class HealthConfig:
    degrade_after_failures: int = 2
    unavailable_after_failures: int = 4
    recover_after_clean_successes: int = 2
    slow_latency_ms: int = 5000

    def __post_init__(self) -> None:
        if self.degrade_after_failures < 1:
            raise ValueError("degrade_after_failures must be >= 1")
        if self.unavailable_after_failures < self.degrade_after_failures:
            raise ValueError("unavailable_after_failures must be >= degrade_after_failures")
        if self.recover_after_clean_successes < 1:
            raise ValueError("recover_after_clean_successes must be >= 1")
        if self.slow_latency_ms < 1:
            raise ValueError("slow_latency_ms must be >= 1")


@dataclass(frozen=True)
class ProbeSample:
    sample_id: str
    started_at: datetime
    completed_at: datetime
    status: CanonicalStatus
    latency_ms: int
    failure_kind: FailureKind | None = None
    source: str = "test"

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id is required")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must be >= started_at")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if self.failure_kind is not None and self.status is not CanonicalStatus.UNKNOWN:
            raise ValueError("a failed probe must normalize canonical status to UNKNOWN")

    @property
    def decisive(self) -> bool:
        return self.failure_kind is None and self.status in (
            CanonicalStatus.LIVE,
            CanonicalStatus.OFFLINE,
        )


@dataclass(frozen=True)
class HealthSnapshot:
    state: HealthState
    consecutive_failures: int
    consecutive_clean_successes: int
    watermark: datetime | None
    seen_sample_ids: frozenset[str]
    last_failure_kind: FailureKind | None
    samples_seen: int
    decisive_samples: int
    unknown_samples: int
    slow_samples: int
    stale_samples: int
    duplicate_samples: int


@dataclass(frozen=True)
class HealthProcessResult:
    accepted: bool
    duplicate: bool
    stale: bool
    previous_state: HealthState
    current_state: HealthState
    canonical_status: CanonicalStatus
    failure_kind: FailureKind | None


class HealthTracker:
    """Hysteretic provider-health tracker for one monitoring scope.

    Ordering uses probe *start* time. A slower request that started before a
    newer probe cannot later degrade health after the newer probe has already
    established the watermark. Equal start timestamps are not classified stale
    because timestamp equality alone does not prove order.
    """

    HARD_FAILURES = frozenset({FailureKind.AUTH, FailureKind.BLOCKED})

    def __init__(self, config: HealthConfig | None = None) -> None:
        self.config = config or HealthConfig()
        self.state = HealthState.STARTING
        self.consecutive_failures = 0
        self.consecutive_clean_successes = 0
        self.watermark: datetime | None = None
        self._seen_sample_ids: set[str] = set()
        self.last_failure_kind: FailureKind | None = None
        self.samples_seen = 0
        self.decisive_samples = 0
        self.unknown_samples = 0
        self.slow_samples = 0
        self.stale_samples = 0
        self.duplicate_samples = 0

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(
            state=self.state,
            consecutive_failures=self.consecutive_failures,
            consecutive_clean_successes=self.consecutive_clean_successes,
            watermark=self.watermark,
            seen_sample_ids=frozenset(self._seen_sample_ids),
            last_failure_kind=self.last_failure_kind,
            samples_seen=self.samples_seen,
            decisive_samples=self.decisive_samples,
            unknown_samples=self.unknown_samples,
            slow_samples=self.slow_samples,
            stale_samples=self.stale_samples,
            duplicate_samples=self.duplicate_samples,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: HealthSnapshot,
        config: HealthConfig | None = None,
    ) -> "HealthTracker":
        tracker = cls(config=config)
        tracker.state = snapshot.state
        tracker.consecutive_failures = snapshot.consecutive_failures
        tracker.consecutive_clean_successes = snapshot.consecutive_clean_successes
        tracker.watermark = snapshot.watermark
        tracker._seen_sample_ids = set(snapshot.seen_sample_ids)
        tracker.last_failure_kind = snapshot.last_failure_kind
        tracker.samples_seen = snapshot.samples_seen
        tracker.decisive_samples = snapshot.decisive_samples
        tracker.unknown_samples = snapshot.unknown_samples
        tracker.slow_samples = snapshot.slow_samples
        tracker.stale_samples = snapshot.stale_samples
        tracker.duplicate_samples = snapshot.duplicate_samples
        tracker._assert_invariants()
        return tracker

    def process_many(self, samples: Iterable[ProbeSample]) -> list[HealthProcessResult]:
        return [self.process(sample) for sample in samples]

    def process(self, sample: ProbeSample) -> HealthProcessResult:
        previous_state = self.state

        if sample.sample_id in self._seen_sample_ids:
            self.duplicate_samples += 1
            return HealthProcessResult(
                accepted=False,
                duplicate=True,
                stale=False,
                previous_state=previous_state,
                current_state=self.state,
                canonical_status=sample.status,
                failure_kind=sample.failure_kind,
            )

        self._seen_sample_ids.add(sample.sample_id)
        self.samples_seen += 1

        if self.watermark is not None and sample.started_at < self.watermark:
            self.stale_samples += 1
            return HealthProcessResult(
                accepted=False,
                duplicate=False,
                stale=True,
                previous_state=previous_state,
                current_state=self.state,
                canonical_status=sample.status,
                failure_kind=sample.failure_kind,
            )

        if self.watermark is None or sample.started_at > self.watermark:
            self.watermark = sample.started_at

        if sample.decisive:
            self.decisive_samples += 1
            self.last_failure_kind = None
            self.consecutive_failures = 0

            if sample.latency_ms >= self.config.slow_latency_ms:
                self.slow_samples += 1
                self.consecutive_clean_successes = 0
                self.state = HealthState.DEGRADED
            else:
                self.consecutive_clean_successes += 1
                if self.state is HealthState.STARTING:
                    self.state = HealthState.HEALTHY
                elif self.state in (HealthState.DEGRADED, HealthState.UNAVAILABLE):
                    if self.consecutive_clean_successes >= self.config.recover_after_clean_successes:
                        self.state = HealthState.HEALTHY
                    else:
                        self.state = HealthState.DEGRADED
                else:
                    self.state = HealthState.HEALTHY
        else:
            self.unknown_samples += 1
            self.consecutive_clean_successes = 0
            self.consecutive_failures += 1
            self.last_failure_kind = sample.failure_kind or FailureKind.EMPTY

            if self.last_failure_kind in self.HARD_FAILURES:
                self.state = HealthState.UNAVAILABLE
            elif self.consecutive_failures >= self.config.unavailable_after_failures:
                self.state = HealthState.UNAVAILABLE
            elif self.consecutive_failures >= self.config.degrade_after_failures:
                self.state = HealthState.DEGRADED

        self._assert_invariants()
        return HealthProcessResult(
            accepted=True,
            duplicate=False,
            stale=False,
            previous_state=previous_state,
            current_state=self.state,
            canonical_status=sample.status,
            failure_kind=sample.failure_kind,
        )

    def _assert_invariants(self) -> None:
        if self.consecutive_failures < 0 or self.consecutive_clean_successes < 0:
            raise AssertionError("health streaks must be non-negative")
        if self.state is HealthState.HEALTHY and self.consecutive_failures >= self.config.degrade_after_failures:
            raise AssertionError("HEALTHY cannot exceed degradation failure threshold")
        if self.state is HealthState.UNAVAILABLE and self.consecutive_clean_successes >= self.config.recover_after_clean_successes:
            raise AssertionError("UNAVAILABLE cannot retain a completed clean recovery streak")


def aggregate_health(states: Iterable[HealthState]) -> HealthState:
    """Aggregate multiple account/source scopes without hiding partial failure."""
    values = tuple(states)
    if not values:
        return HealthState.STARTING
    if all(value is HealthState.HEALTHY for value in values):
        return HealthState.HEALTHY
    if all(value is HealthState.UNAVAILABLE for value in values):
        return HealthState.UNAVAILABLE
    if all(value is HealthState.STARTING for value in values):
        return HealthState.STARTING
    return HealthState.DEGRADED
