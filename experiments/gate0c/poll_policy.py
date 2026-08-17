#!/usr/bin/env python3
"""Stage Letter Gate 0C-2 — pure polling / retry / backoff policy.

The policy decides *when* a provider route should be probed again. It does not
perform HTTP requests, does not alter HealthTracker state, and intentionally has
no creator LIVE/OFFLINE/UNKNOWN output.

Gate timing defaults are acceptance-test parameters, not production tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from platform_health import FailureKind, HealthState


class PollMode(str, Enum):
    NORMAL = "NORMAL"
    CONSERVATIVE = "CONSERVATIVE"
    RECOVERY_PROBE = "RECOVERY_PROBE"


@dataclass(frozen=True)
class PollPolicyConfig:
    starting_interval_s: int = 30
    healthy_interval_s: int = 60
    degraded_interval_s: int = 120
    unavailable_base_interval_s: int = 180
    unavailable_max_interval_s: int = 1800
    rate_limit_min_cooldown_s: int = 600
    hard_failure_min_cooldown_s: int = 900
    jitter_fraction: float = 0.10

    def __post_init__(self) -> None:
        positive = {
            "starting_interval_s": self.starting_interval_s,
            "healthy_interval_s": self.healthy_interval_s,
            "degraded_interval_s": self.degraded_interval_s,
            "unavailable_base_interval_s": self.unavailable_base_interval_s,
            "unavailable_max_interval_s": self.unavailable_max_interval_s,
            "rate_limit_min_cooldown_s": self.rate_limit_min_cooldown_s,
            "hard_failure_min_cooldown_s": self.hard_failure_min_cooldown_s,
        }
        for name, value in positive.items():
            if value < 1:
                raise ValueError(f"{name} must be >= 1")

        if self.unavailable_max_interval_s < self.unavailable_base_interval_s:
            raise ValueError(
                "unavailable_max_interval_s must be >= unavailable_base_interval_s"
            )
        if not 0.0 <= self.jitter_fraction <= 0.5:
            raise ValueError("jitter_fraction must be between 0.0 and 0.5")


@dataclass(frozen=True)
class PollContext:
    health_state: HealthState
    failure_kind: FailureKind | None = None
    consecutive_failures: int = 0
    # Deterministic input supplied by a scheduler/hash/random source. Keeping
    # randomness outside this policy makes identical inputs reproducible.
    jitter_unit: float = 0.0

    def __post_init__(self) -> None:
        if self.consecutive_failures < 0:
            raise ValueError("consecutive_failures must be >= 0")
        if not -1.0 <= self.jitter_unit <= 1.0:
            raise ValueError("jitter_unit must be between -1.0 and 1.0")


@dataclass(frozen=True)
class PollDecision:
    delay_s: int
    base_delay_s: int
    minimum_cooldown_s: int
    mode: PollMode
    backoff_step: int
    capped: bool


def decide_poll(
    context: PollContext,
    config: PollPolicyConfig | None = None,
) -> PollDecision:
    """Return a deterministic next-poll decision for one provider route."""

    policy = config or PollPolicyConfig()

    if context.health_state is HealthState.STARTING:
        base_delay = policy.starting_interval_s
        mode = PollMode.NORMAL
        backoff_step = 0
        capped = False
    elif context.health_state is HealthState.HEALTHY:
        base_delay = policy.healthy_interval_s
        mode = PollMode.NORMAL
        backoff_step = 0
        capped = False
    elif context.health_state is HealthState.DEGRADED:
        base_delay = policy.degraded_interval_s
        mode = PollMode.CONSERVATIVE
        backoff_step = 0
        capped = False
    elif context.health_state is HealthState.UNAVAILABLE:
        # Once a route is unavailable, every additional failure increases the
        # recovery-probe backoff. The exact health transition threshold remains
        # owned by HealthTracker; this policy only consumes the current streak.
        backoff_step = max(context.consecutive_failures - 1, 0)
        raw = policy.unavailable_base_interval_s * (2**backoff_step)
        capped = raw > policy.unavailable_max_interval_s
        base_delay = min(raw, policy.unavailable_max_interval_s)
        mode = PollMode.RECOVERY_PROBE
    else:  # pragma: no cover - Enum exhaustiveness guard
        raise ValueError(f"unsupported health state: {context.health_state}")

    minimum_cooldown = 0
    if context.failure_kind is FailureKind.RATE_LIMIT:
        minimum_cooldown = policy.rate_limit_min_cooldown_s
    elif context.failure_kind in (FailureKind.AUTH, FailureKind.BLOCKED):
        minimum_cooldown = policy.hard_failure_min_cooldown_s

    # Jitter is symmetric around the base decision. For UNAVAILABLE recovery
    # probes, jitter itself may not escape the exponential-backoff ceiling.
    # A provider-safety minimum cooldown is applied after that ceiling and may
    # intentionally be longer than the generic backoff cap if configured so.
    jitter_multiplier = 1.0 + policy.jitter_fraction * context.jitter_unit
    jittered_unbounded = max(1, round(base_delay * jitter_multiplier))
    if context.health_state is HealthState.UNAVAILABLE:
        if jittered_unbounded > policy.unavailable_max_interval_s:
            capped = True
        jittered = min(jittered_unbounded, policy.unavailable_max_interval_s)
    else:
        jittered = jittered_unbounded

    delay = max(jittered, minimum_cooldown)

    return PollDecision(
        delay_s=delay,
        base_delay_s=base_delay,
        minimum_cooldown_s=minimum_cooldown,
        mode=mode,
        backoff_step=backoff_step,
        capped=capped,
    )
