"""Formal bounded monitoring scheduler for Gate 1.4-3.

This module owns cadence/concurrency/retry mechanics only. It delegates target
selection and probe persistence to application services, preserves one logical
probe_id across retries, and never interprets provider metadata as live truth.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from stage_letter.application.services.monitoring import MonitoringTargetApplicationService
from stage_letter.application.services.monitoring_probe import (
    MonitoringProbeApplicationService,
    MonitoringProbeRequest,
    MonitoringProbeResult,
)
from stage_letter.domain.creators import PlatformAccount

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class MonitoringSchedulerPolicy:
    """Deterministic scheduler policy; provider-specific limits stay outside truth."""

    cadence_seconds: float = 30.0
    max_concurrency: int = 16
    per_platform_concurrency: int = 4
    max_attempts: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 8.0
    page_size: int = 100

    def __post_init__(self) -> None:
        if self.cadence_seconds <= 0:
            raise ValueError("cadence_seconds must be positive")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.per_platform_concurrency < 1:
            raise ValueError("per_platform_concurrency must be at least 1")
        if self.per_platform_concurrency > self.max_concurrency:
            raise ValueError("per_platform_concurrency cannot exceed max_concurrency")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= base_backoff_seconds")
        if self.page_size < 1 or self.page_size > MonitoringTargetApplicationService.MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be between 1 and {MonitoringTargetApplicationService.MAX_PAGE_SIZE}"
            )

    def backoff_seconds(self, failed_attempt: int) -> float:
        """Return deterministic capped exponential delay after a failed attempt."""

        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        delay = self.base_backoff_seconds * (2 ** (failed_attempt - 1))
        return min(delay, self.max_backoff_seconds)


@dataclass(frozen=True)
class ScheduledProbeOutcome:
    request: MonitoringProbeRequest
    platform: str
    attempts: int
    result: MonitoringProbeResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.error is None


def make_probe_id(cycle_id: str, account_id: str) -> str:
    """Create one stable bounded logical probe id for a cycle/account pair."""

    cycle = cycle_id.strip()
    account = account_id.strip()
    if not cycle:
        raise ValueError("cycle_id is required")
    if not account:
        raise ValueError("account_id is required")
    digest = hashlib.sha256(f"{cycle}\0{account}".encode("utf-8")).hexdigest()
    return f"monitor:{digest}"


class MonitoringScheduler:
    """Run deterministic monitoring cycles with bounded, conservative retries.

    Single-flight is guaranteed inside one scheduler process for the same
    `(account_id, probe_id)`. Retries reuse the exact same request. Cross-process
    durable duplicate prevention remains protected by the probe persistence
    contract and is finalized by the later durability acceptance slice.
    """

    RETRYABLE_EXCEPTIONS = (TimeoutError, ConnectionError)

    def __init__(
        self,
        targets: MonitoringTargetApplicationService,
        probes: MonitoringProbeApplicationService,
        *,
        policy: MonitoringSchedulerPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._targets = targets
        self._probes = probes
        self.policy = policy or MonitoringSchedulerPolicy()
        self._sleep = sleep
        self._global_limit = asyncio.Semaphore(self.policy.max_concurrency)
        self._platform_limits: dict[str, asyncio.Semaphore] = {}
        self._inflight: dict[tuple[str, str], asyncio.Task[ScheduledProbeOutcome]] = {}

    def _platform_limit(self, platform: str) -> asyncio.Semaphore:
        semaphore = self._platform_limits.get(platform)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.policy.per_platform_concurrency)
            self._platform_limits[platform] = semaphore
        return semaphore

    async def run_target(
        self,
        *,
        cycle_id: str,
        account: PlatformAccount,
    ) -> ScheduledProbeOutcome:
        request = MonitoringProbeRequest(
            probe_id=make_probe_id(cycle_id, account.account_id),
            account_id=account.account_id,
        )
        key = (request.account_id, request.probe_id)
        existing = self._inflight.get(key)
        if existing is not None:
            return await existing

        task = asyncio.create_task(self._run_with_retries(account, request))
        self._inflight[key] = task
        try:
            return await task
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _run_with_retries(
        self,
        account: PlatformAccount,
        request: MonitoringProbeRequest,
    ) -> ScheduledProbeOutcome:
        last_error: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                async with self._global_limit:
                    async with self._platform_limit(account.platform):
                        result = await self._probes.execute(request)
                return ScheduledProbeOutcome(
                    request=request,
                    platform=account.platform,
                    attempts=attempt,
                    result=result,
                )
            except self.RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= self.policy.max_attempts:
                    break
                await self._sleep(self.policy.backoff_seconds(attempt))
            except Exception as exc:
                return ScheduledProbeOutcome(
                    request=request,
                    platform=account.platform,
                    attempts=attempt,
                    error=exc,
                )

        assert last_error is not None
        return ScheduledProbeOutcome(
            request=request,
            platform=account.platform,
            attempts=self.policy.max_attempts,
            error=last_error,
        )

    async def run_cycle(self, cycle_id: str) -> tuple[ScheduledProbeOutcome, ...]:
        """Discover every eligible account exactly once and run one logical probe."""

        # Validate before any target-discovery I/O.
        make_probe_id(cycle_id, "validation")

        outcomes: list[ScheduledProbeOutcome] = []
        after_account_id: str | None = None
        while True:
            page = await self._targets.list_targets(
                after_account_id=after_account_id,
                limit=self.policy.page_size,
            )
            if not page:
                break

            page_outcomes = await asyncio.gather(
                *(self.run_target(cycle_id=cycle_id, account=account) for account in page)
            )
            outcomes.extend(page_outcomes)
            after_account_id = page[-1].account_id
            if len(page) < self.policy.page_size:
                break

        return tuple(outcomes)
