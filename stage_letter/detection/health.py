"""Pure Gate 2.4 circuit-breaker policy for detection platform health."""
from __future__ import annotations

from dataclasses import dataclass

from stage_letter.detection.contracts import PlatformHealthState


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    degraded_failure_threshold: int = 5
    disabled_failure_threshold: int = 20
    degraded_interval_multiplier: int = 5

    def __post_init__(self) -> None:
        if self.degraded_failure_threshold < 1:
            raise ValueError("degraded_failure_threshold must be at least 1")
        if self.disabled_failure_threshold <= self.degraded_failure_threshold:
            raise ValueError("disabled_failure_threshold must be greater than degraded threshold")
        if self.degraded_interval_multiplier < 1:
            raise ValueError("degraded_interval_multiplier must be at least 1")


def normalize_platform_health_state(raw: str | None) -> PlatformHealthState:
    """Normalize operational health metadata without increasing provider pressure."""

    if raw is None or not raw.strip():
        return PlatformHealthState.HEALTHY
    try:
        return PlatformHealthState(raw.strip().upper())
    except ValueError:
        # Corrupt health metadata must not silently restore full-rate polling.
        return PlatformHealthState.DEGRADED


def state_after_probe(
    *,
    current: PlatformHealthState,
    success: bool,
    consecutive_failures: int,
    policy: CircuitBreakerPolicy,
) -> PlatformHealthState:
    """Return the platform state after one persisted operational probe result.

    DISABLED is sticky until an explicit administrative enable. A successful
    half-open probe from DEGRADED restores HEALTHY. Failures trip DEGRADED at 5
    and DISABLED at 20 by default.
    """

    if consecutive_failures < 0:
        raise ValueError("consecutive_failures must be non-negative")
    if current is PlatformHealthState.DISABLED:
        return PlatformHealthState.DISABLED
    if success:
        return PlatformHealthState.HEALTHY
    if consecutive_failures >= policy.disabled_failure_threshold:
        return PlatformHealthState.DISABLED
    if current is PlatformHealthState.DEGRADED:
        return PlatformHealthState.DEGRADED
    if consecutive_failures >= policy.degraded_failure_threshold:
        return PlatformHealthState.DEGRADED
    return PlatformHealthState.HEALTHY


def cadence_multiplier(
    state: PlatformHealthState,
    *,
    policy: CircuitBreakerPolicy,
) -> int | None:
    """Return scheduling multiplier; None means automatic probing is disabled."""

    if state is PlatformHealthState.DISABLED:
        return None
    if state is PlatformHealthState.DEGRADED:
        return policy.degraded_interval_multiplier
    return 1
