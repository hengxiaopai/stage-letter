"""Gate 2.2 per-platform execution isolation, rate limiting, and retry policy.

This module coordinates provider operations only. It never interprets provider
failures as canonical live truth and never writes live/session/event state.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from stage_letter.infrastructure.platforms.failures import (
    ProviderFailureKind,
    ProviderOperationError,
)

T = TypeVar("T")
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Operation = Callable[[], Awaitable[T]]


class RetryAction(str, Enum):
    RETRY = "RETRY"
    STOP = "STOP"


@dataclass(frozen=True)
class RetryDecision:
    action: RetryAction
    reason: str


_TRANSIENT_PROVIDER_FAILURES = frozenset(
    {
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.NETWORK,
        ProviderFailureKind.RATE_LIMITED,
        ProviderFailureKind.UPSTREAM_ERROR,
    }
)


def classify_retry(exc: BaseException) -> RetryDecision:
    """Classify execution failures conservatively.

    Only failures with explicit transient semantics are retried. Provider
    ambiguity/auth/schema/parse/not-found evidence is not automatically retried
    here and is never translated to OFFLINE.
    """

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return RetryDecision(RetryAction.RETRY, type(exc).__name__)
    if isinstance(exc, ProviderOperationError):
        kind = exc.failure.kind
        if kind in _TRANSIENT_PROVIDER_FAILURES:
            return RetryDecision(RetryAction.RETRY, kind.value)
        return RetryDecision(RetryAction.STOP, kind.value)
    return RetryDecision(RetryAction.STOP, type(exc).__name__)


@dataclass(frozen=True)
class PlatformRuntimePolicy:
    max_global_concurrency: int = 16
    max_platform_concurrency: int = 4
    requests_per_second: float = 1.0
    max_attempts: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_global_concurrency < 1:
            raise ValueError("max_global_concurrency must be at least 1")
        if self.max_platform_concurrency < 1:
            raise ValueError("max_platform_concurrency must be at least 1")
        if self.max_platform_concurrency > self.max_global_concurrency:
            raise ValueError("max_platform_concurrency cannot exceed global concurrency")
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= base_backoff_seconds")

    def backoff_seconds(self, failed_attempt: int) -> float:
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        return min(
            self.base_backoff_seconds * (2 ** (failed_attempt - 1)),
            self.max_backoff_seconds,
        )


@dataclass(frozen=True)
class RuntimeExecutionOutcome(Generic[T]):
    platform: str
    attempts: int
    value: T | None = None
    error: Exception | None = None
    last_retry_decision: RetryDecision | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class _PlatformStartRateLimiter:
    """Serialize provider start times per platform without consuming worker slots."""

    def __init__(self, rps: float, *, sleep: Sleep, clock: Clock) -> None:
        self._interval = 1.0 / rps
        self._sleep = sleep
        self._clock = clock
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = self._next_allowed - now
            if delay > 0:
                await self._sleep(delay)
                now = self._clock()
            self._next_allowed = max(self._next_allowed, now) + self._interval


class DetectionRuntimeCoordinator:
    """Execute provider operations with per-platform isolation and bounded retries."""

    def __init__(
        self,
        *,
        default_policy: PlatformRuntimePolicy | None = None,
        platform_policies: dict[str, PlatformRuntimePolicy] | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self.default_policy = default_policy or PlatformRuntimePolicy()
        self._platform_policies = dict(platform_policies or {})
        self._sleep = sleep
        self._clock = clock
        self._global_limit = asyncio.Semaphore(self.default_policy.max_global_concurrency)
        self._platform_limits: dict[str, asyncio.Semaphore] = {}
        self._rate_limiters: dict[str, _PlatformStartRateLimiter] = {}

    def policy_for(self, platform: str) -> PlatformRuntimePolicy:
        if not platform.strip():
            raise ValueError("platform is required")
        policy = self._platform_policies.get(platform, self.default_policy)
        if policy.max_global_concurrency != self.default_policy.max_global_concurrency:
            raise ValueError("platform policy must use the coordinator global concurrency")
        return policy

    def _platform_limit(self, platform: str) -> asyncio.Semaphore:
        limit = self._platform_limits.get(platform)
        if limit is None:
            limit = asyncio.Semaphore(self.policy_for(platform).max_platform_concurrency)
            self._platform_limits[platform] = limit
        return limit

    def _rate_limiter(self, platform: str) -> _PlatformStartRateLimiter:
        limiter = self._rate_limiters.get(platform)
        if limiter is None:
            limiter = _PlatformStartRateLimiter(
                self.policy_for(platform).requests_per_second,
                sleep=self._sleep,
                clock=self._clock,
            )
            self._rate_limiters[platform] = limiter
        return limiter

    async def execute(self, platform: str, operation: Operation[T]) -> RuntimeExecutionOutcome[T]:
        policy = self.policy_for(platform)
        for attempt in range(1, policy.max_attempts + 1):
            try:
                # Waiting for a platform's rate window must not consume scarce
                # global/per-platform execution slots.
                await self._rate_limiter(platform).acquire()
                # Acquire platform capacity first so a saturated platform cannot
                # occupy every global slot while waiting on its own queue.
                async with self._platform_limit(platform):
                    async with self._global_limit:
                        value = await operation()
                return RuntimeExecutionOutcome(
                    platform=platform,
                    attempts=attempt,
                    value=value,
                )
            except Exception as exc:
                decision = classify_retry(exc)
                if decision.action is RetryAction.STOP or attempt >= policy.max_attempts:
                    return RuntimeExecutionOutcome(
                        platform=platform,
                        attempts=attempt,
                        error=exc,
                        last_retry_decision=decision,
                    )
                await self._sleep(policy.backoff_seconds(attempt))

        raise AssertionError("runtime retry loop must always return")
