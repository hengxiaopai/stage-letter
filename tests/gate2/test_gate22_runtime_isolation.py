from __future__ import annotations

import asyncio

import pytest

from stage_letter.infrastructure.detection.runtime import (
    DetectionRuntimeCoordinator,
    PlatformRuntimePolicy,
    RetryAction,
    classify_retry,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)


def _provider_error(kind: ProviderFailureKind) -> ProviderOperationError:
    return ProviderOperationError(ProviderFailure(kind=kind, source="test.provider"))


def test_plain_transport_failures_are_retryable() -> None:
    assert classify_retry(TimeoutError()).action is RetryAction.RETRY
    assert classify_retry(ConnectionError()).action is RetryAction.RETRY


def test_explicit_transient_provider_failures_are_retryable() -> None:
    for kind in (
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.NETWORK,
        ProviderFailureKind.RATE_LIMITED,
        ProviderFailureKind.UPSTREAM_ERROR,
    ):
        decision = classify_retry(_provider_error(kind))
        assert decision.action is RetryAction.RETRY
        assert decision.reason == kind.value


def test_ambiguous_auth_parse_and_schema_failures_are_not_blindly_retried() -> None:
    for kind in (
        ProviderFailureKind.AUTH_REQUIRED,
        ProviderFailureKind.FORBIDDEN,
        ProviderFailureKind.CAPTCHA_REQUIRED,
        ProviderFailureKind.PARSE_ERROR,
        ProviderFailureKind.SCHEMA_DRIFT,
        ProviderFailureKind.AMBIGUOUS,
        ProviderFailureKind.NOT_FOUND,
        ProviderFailureKind.UNKNOWN,
    ):
        decision = classify_retry(_provider_error(kind))
        assert decision.action is RetryAction.STOP


def test_runtime_policy_validation_and_capped_backoff() -> None:
    policy = PlatformRuntimePolicy(
        max_global_concurrency=4,
        max_platform_concurrency=2,
        requests_per_second=2.0,
        max_attempts=4,
        base_backoff_seconds=1.0,
        max_backoff_seconds=2.5,
    )
    assert policy.backoff_seconds(1) == 1.0
    assert policy.backoff_seconds(2) == 2.0
    assert policy.backoff_seconds(3) == 2.5
    with pytest.raises(ValueError):
        PlatformRuntimePolicy(max_global_concurrency=0)
    with pytest.raises(ValueError):
        PlatformRuntimePolicy(max_global_concurrency=1, max_platform_concurrency=2)
    with pytest.raises(ValueError):
        PlatformRuntimePolicy(requests_per_second=0)


@pytest.mark.asyncio
async def test_rate_limiter_spaces_provider_starts_without_network_calls() -> None:
    now = 0.0
    starts: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    def clock() -> float:
        return now

    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=2.0,
            max_attempts=1,
        ),
        sleep=sleep,
        clock=clock,
    )

    async def operation() -> str:
        starts.append(clock())
        return "ok"

    assert (await coordinator.execute("douyin", operation)).succeeded
    assert (await coordinator.execute("douyin", operation)).succeeded
    assert (await coordinator.execute("douyin", operation)).succeeded
    assert starts == [0.0, 0.5, 1.0]


@pytest.mark.asyncio
async def test_retryable_failure_retries_with_capped_backoff_and_then_succeeds() -> None:
    attempts = 0
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=3,
            base_backoff_seconds=1,
            max_backoff_seconds=8,
        ),
        sleep=sleep,
    )

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _provider_error(ProviderFailureKind.UPSTREAM_ERROR)
        return "ok"

    outcome = await coordinator.execute("bilibili", operation)
    assert outcome.succeeded
    assert outcome.value == "ok"
    assert outcome.attempts == 3
    assert attempts == 3
    assert 1.0 in delays and 2.0 in delays


@pytest.mark.asyncio
async def test_non_retryable_provider_failure_stops_after_one_attempt() -> None:
    attempts = 0

    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(requests_per_second=1_000_000)
    )

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise _provider_error(ProviderFailureKind.AUTH_REQUIRED)

    outcome = await coordinator.execute("huya", operation)
    assert not outcome.succeeded
    assert outcome.attempts == 1
    assert attempts == 1
    assert outcome.last_retry_decision is not None
    assert outcome.last_retry_decision.action is RetryAction.STOP


@pytest.mark.asyncio
async def test_retry_exhaustion_preserves_error_without_fabricating_value() -> None:
    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            requests_per_second=1_000_000,
            max_attempts=2,
            base_backoff_seconds=0,
        )
    )

    async def operation() -> str:
        raise ConnectionError("provider unavailable")

    outcome = await coordinator.execute("douyu", operation)
    assert not outcome.succeeded
    assert outcome.attempts == 2
    assert outcome.value is None
    assert isinstance(outcome.error, ConnectionError)
    assert outcome.last_retry_decision is not None
    assert outcome.last_retry_decision.action is RetryAction.RETRY


@pytest.mark.asyncio
async def test_saturated_platform_does_not_block_other_platform_progress() -> None:
    first_douyin_started = asyncio.Event()
    bili_started = asyncio.Event()
    release = asyncio.Event()
    douyin_calls = 0

    coordinator = DetectionRuntimeCoordinator(
        default_policy=PlatformRuntimePolicy(
            max_global_concurrency=2,
            max_platform_concurrency=1,
            requests_per_second=1_000_000,
            max_attempts=1,
        )
    )

    async def douyin_operation() -> str:
        nonlocal douyin_calls
        douyin_calls += 1
        if douyin_calls == 1:
            first_douyin_started.set()
        await release.wait()
        return "douyin"

    async def bili_operation() -> str:
        bili_started.set()
        return "bilibili"

    first = asyncio.create_task(coordinator.execute("douyin", douyin_operation))
    await first_douyin_started.wait()
    second = asyncio.create_task(coordinator.execute("douyin", douyin_operation))
    bili = asyncio.create_task(coordinator.execute("bilibili", bili_operation))

    await asyncio.wait_for(bili_started.wait(), timeout=1.0)
    assert (await bili).succeeded
    assert douyin_calls == 1

    release.set()
    first_outcome, second_outcome = await asyncio.gather(first, second)
    assert first_outcome.succeeded
    assert second_outcome.succeeded
    assert douyin_calls == 2
