#!/usr/bin/env python3
"""Gate 0D-3 — bounded delivery retry / terminal-state semantics.

This module composes one logical notification delivery with normalized provider
results. It is deliberately provider-agnostic and does not call WeChat.

A critical safety boundary is explicit: an attempt is persisted as IN_FLIGHT
*before* the external send. If the process restarts while that attempt is still
in flight, the delivery becomes AMBIGUOUS and is not blindly retried. Without a
provider-side idempotency/reconciliation guarantee, blindly retrying such an
attempt could duplicate a user notification.

No type in this module can mutate creator LIVE/OFFLINE state or LiveSession.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from notification_truth import DeliveryKey, GrantState, NotificationDelivery
from provider_result import (
    NormalizedProviderResult,
    ProviderOutcome,
    RetryClass,
    apply_grant_effect,
)


class ExecutionState(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    WAITING_RETRY = "WAITING_RETRY"
    WAITING_AUTH = "WAITING_AUTH"
    BLOCKED_CONFIG = "BLOCKED_CONFIG"
    SENT = "SENT"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class RetryPolicy:
    max_total_attempts: int = 5
    transient_base_delay_seconds: int = 30
    transient_max_delay_seconds: int = 600
    default_cooldown_seconds: int = 300

    def __post_init__(self) -> None:
        if self.max_total_attempts < 1:
            raise ValueError("max_total_attempts must be >= 1")
        if self.transient_base_delay_seconds < 1:
            raise ValueError("transient_base_delay_seconds must be >= 1")
        if self.transient_max_delay_seconds < self.transient_base_delay_seconds:
            raise ValueError("transient_max_delay_seconds must be >= transient_base_delay_seconds")
        if self.default_cooldown_seconds < 1:
            raise ValueError("default_cooldown_seconds must be >= 1")


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None = None
    outcome: ProviderOutcome | None = None
    provider_code: str | None = None
    provider_message: str | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id is required")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.completed_at is None and self.outcome is not None:
            raise ValueError("incomplete attempt cannot have an outcome")
        if self.completed_at is not None and self.outcome is None:
            raise ValueError("completed attempt requires an outcome")


@dataclass(frozen=True)
class DeliveryRuntimeSnapshot:
    key: DeliveryKey
    account_id: str
    session_id: str
    state: ExecutionState
    grant_state: GrantState
    attempts: tuple[AttemptRecord, ...]
    next_attempt_at: datetime | None
    terminal_outcome: ProviderOutcome | None


@dataclass(frozen=True)
class BeginAttemptResult:
    started: bool
    attempt: AttemptRecord | None


@dataclass(frozen=True)
class CompleteAttemptResult:
    applied: bool
    duplicate: bool
    state: ExecutionState
    grant_state: GrantState
    next_attempt_at: datetime | None


class DeliveryRetryMachine:
    """Deterministic runtime for one logical NotificationDelivery."""

    def __init__(
        self,
        *,
        key: DeliveryKey,
        account_id: str,
        session_id: str,
        grant_state: GrantState,
        policy: RetryPolicy | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        if not session_id:
            raise ValueError("session_id is required")
        self.key = key
        self.account_id = account_id
        self.session_id = session_id
        self.grant_state = grant_state
        self.policy = policy or RetryPolicy()
        self.state = ExecutionState.PENDING
        self.attempts: list[AttemptRecord] = []
        self.next_attempt_at: datetime | None = None
        self.terminal_outcome: ProviderOutcome | None = None

    @classmethod
    def from_delivery(
        cls,
        delivery: NotificationDelivery,
        *,
        grant_state: GrantState,
        policy: RetryPolicy | None = None,
    ) -> "DeliveryRetryMachine":
        return cls(
            key=delivery.key,
            account_id=delivery.account_id,
            session_id=delivery.session_id,
            grant_state=grant_state,
            policy=policy,
        )

    def snapshot(self) -> DeliveryRuntimeSnapshot:
        return DeliveryRuntimeSnapshot(
            key=self.key,
            account_id=self.account_id,
            session_id=self.session_id,
            state=self.state,
            grant_state=self.grant_state,
            attempts=tuple(self.attempts),
            next_attempt_at=self.next_attempt_at,
            terminal_outcome=self.terminal_outcome,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: DeliveryRuntimeSnapshot,
        *,
        policy: RetryPolicy | None = None,
    ) -> "DeliveryRetryMachine":
        machine = cls(
            key=snapshot.key,
            account_id=snapshot.account_id,
            session_id=snapshot.session_id,
            grant_state=snapshot.grant_state,
            policy=policy,
        )
        machine.state = snapshot.state
        machine.attempts = list(snapshot.attempts)
        machine.next_attempt_at = snapshot.next_attempt_at
        machine.terminal_outcome = snapshot.terminal_outcome
        machine._validate_snapshot()

        # Crash/restart safety: an unresolved external side effect is ambiguous.
        # Never automatically convert it back to PENDING/WAITING_RETRY.
        if machine.state is ExecutionState.IN_FLIGHT:
            machine.state = ExecutionState.AMBIGUOUS
            machine.next_attempt_at = None

        machine._assert_invariants()
        return machine

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            ExecutionState.SENT,
            ExecutionState.FAILED_TERMINAL,
            ExecutionState.AMBIGUOUS,
        )

    def begin_attempt(self, *, attempt_id: str, started_at: datetime) -> BeginAttemptResult:
        if not attempt_id:
            raise ValueError("attempt_id is required")
        if any(item.attempt_id == attempt_id for item in self.attempts):
            raise ValueError("attempt_id has already been used")
        if self.state in (
            ExecutionState.SENT,
            ExecutionState.FAILED_TERMINAL,
            ExecutionState.AMBIGUOUS,
            ExecutionState.IN_FLIGHT,
            ExecutionState.WAITING_AUTH,
            ExecutionState.BLOCKED_CONFIG,
        ):
            return BeginAttemptResult(False, None)
        if self.state is ExecutionState.WAITING_RETRY:
            if self.next_attempt_at is None:
                raise AssertionError("WAITING_RETRY requires next_attempt_at")
            if started_at < self.next_attempt_at:
                return BeginAttemptResult(False, None)
        if self.attempt_count >= self.policy.max_total_attempts:
            self._terminate_for_budget()
            return BeginAttemptResult(False, None)

        attempt = AttemptRecord(
            attempt_id=attempt_id,
            attempt_number=self.attempt_count + 1,
            started_at=started_at,
        )
        self.attempts.append(attempt)
        self.state = ExecutionState.IN_FLIGHT
        self.next_attempt_at = None
        self._assert_invariants()
        return BeginAttemptResult(True, attempt)

    def complete_attempt(
        self,
        *,
        attempt_id: str,
        result: NormalizedProviderResult,
        completed_at: datetime,
    ) -> CompleteAttemptResult:
        index = self._find_attempt_index(attempt_id)
        existing = self.attempts[index]

        if existing.completed_at is not None:
            same = (
                existing.outcome is result.outcome
                and existing.provider_code == result.provider_code
                and existing.provider_message == result.provider_message
            )
            if not same:
                raise ValueError("attempt completion replay conflicts with stored outcome")
            return CompleteAttemptResult(
                applied=False,
                duplicate=True,
                state=self.state,
                grant_state=self.grant_state,
                next_attempt_at=self.next_attempt_at,
            )

        if self.state is not ExecutionState.IN_FLIGHT:
            raise ValueError("only IN_FLIGHT delivery can complete an unresolved attempt")
        if index != len(self.attempts) - 1:
            raise ValueError("only the latest unresolved attempt may complete")
        if completed_at < existing.started_at:
            raise ValueError("completed_at cannot precede started_at")

        self.attempts[index] = replace(
            existing,
            completed_at=completed_at,
            outcome=result.outcome,
            provider_code=result.provider_code,
            provider_message=result.provider_message,
        )
        self.grant_state = apply_grant_effect(self.grant_state, result)
        self.next_attempt_at = None
        self.terminal_outcome = None

        if result.success:
            self.state = ExecutionState.SENT
            self.terminal_outcome = result.outcome
        elif result.terminal_for_delivery:
            self.state = ExecutionState.FAILED_TERMINAL
            self.terminal_outcome = result.outcome
        elif result.retry_class is RetryClass.AFTER_AUTH:
            self.state = ExecutionState.WAITING_AUTH
        elif result.retry_class is RetryClass.AFTER_CONFIG_FIX:
            self.state = ExecutionState.BLOCKED_CONFIG
        elif result.retryable:
            if self.attempt_count >= self.policy.max_total_attempts:
                self.state = ExecutionState.FAILED_TERMINAL
                self.terminal_outcome = result.outcome
            else:
                delay = self._retry_delay_seconds(result)
                self.state = ExecutionState.WAITING_RETRY
                self.next_attempt_at = completed_at + timedelta(seconds=delay)
        else:
            raise AssertionError("unhandled provider-result semantics")

        self._assert_invariants()
        return CompleteAttemptResult(
            applied=True,
            duplicate=False,
            state=self.state,
            grant_state=self.grant_state,
            next_attempt_at=self.next_attempt_at,
        )

    def resume_after_auth(self) -> bool:
        if self.state is not ExecutionState.WAITING_AUTH:
            return False
        if self.attempt_count >= self.policy.max_total_attempts:
            self._terminate_for_budget()
            return False
        self.state = ExecutionState.PENDING
        self._assert_invariants()
        return True

    def resume_after_config_fix(self) -> bool:
        if self.state is not ExecutionState.BLOCKED_CONFIG:
            return False
        if self.attempt_count >= self.policy.max_total_attempts:
            self._terminate_for_budget()
            return False
        self.state = ExecutionState.PENDING
        self._assert_invariants()
        return True

    def _retry_delay_seconds(self, result: NormalizedProviderResult) -> int:
        if result.retry_class is RetryClass.AFTER_COOLDOWN:
            return (
                result.retry_after_seconds
                if result.retry_after_seconds is not None
                else self.policy.default_cooldown_seconds
            )

        if result.retry_class is RetryClass.TRANSIENT:
            transient_failures = sum(
                1
                for attempt in self.attempts
                if attempt.outcome in (ProviderOutcome.NETWORK_ERROR, ProviderOutcome.PROVIDER_ERROR)
            )
            exponential = self.policy.transient_base_delay_seconds * (2 ** max(0, transient_failures - 1))
            delay = min(exponential, self.policy.transient_max_delay_seconds)
            if result.retry_after_seconds is not None:
                delay = max(delay, result.retry_after_seconds)
            return delay

        raise AssertionError("retry delay requested for non-timed retry class")

    def _terminate_for_budget(self) -> None:
        last_outcome = next(
            (attempt.outcome for attempt in reversed(self.attempts) if attempt.outcome is not None),
            None,
        )
        if last_outcome is None:
            raise AssertionError("attempt budget cannot be exhausted without a completed outcome")
        self.state = ExecutionState.FAILED_TERMINAL
        self.next_attempt_at = None
        self.terminal_outcome = last_outcome
        self._assert_invariants()

    def _find_attempt_index(self, attempt_id: str) -> int:
        for index, item in enumerate(self.attempts):
            if item.attempt_id == attempt_id:
                return index
        raise ValueError("unknown attempt_id")

    def _validate_snapshot(self) -> None:
        ids: set[str] = set()
        for expected_number, attempt in enumerate(self.attempts, start=1):
            if attempt.attempt_id in ids:
                raise ValueError("snapshot contains duplicate attempt_id")
            ids.add(attempt.attempt_id)
            if attempt.attempt_number != expected_number:
                raise ValueError("snapshot attempt numbers must be contiguous")
        if len(self.attempts) > self.policy.max_total_attempts:
            raise ValueError("snapshot exceeds max_total_attempts")
        unresolved = [item for item in self.attempts if item.completed_at is None]
        if len(unresolved) > 1:
            raise ValueError("snapshot contains multiple unresolved attempts")
        if unresolved and unresolved[0] is not self.attempts[-1]:
            raise ValueError("only latest snapshot attempt may be unresolved")
        if self.state is ExecutionState.IN_FLIGHT and len(unresolved) != 1:
            raise ValueError("IN_FLIGHT snapshot requires one unresolved attempt")
        if self.state is not ExecutionState.IN_FLIGHT and unresolved:
            raise ValueError("unresolved attempt requires IN_FLIGHT snapshot state")

    def _assert_invariants(self) -> None:
        if self.state is ExecutionState.IN_FLIGHT:
            if not self.attempts or self.attempts[-1].completed_at is not None:
                raise AssertionError("IN_FLIGHT requires latest unresolved attempt")
        if self.state is ExecutionState.WAITING_RETRY:
            if self.next_attempt_at is None:
                raise AssertionError("WAITING_RETRY requires next_attempt_at")
        elif self.next_attempt_at is not None:
            raise AssertionError("only WAITING_RETRY may have next_attempt_at")
        if self.state in (ExecutionState.SENT, ExecutionState.FAILED_TERMINAL):
            if self.terminal_outcome is None:
                raise AssertionError("terminal resolved state requires terminal_outcome")
        if self.state is ExecutionState.SENT and self.grant_state is not GrantState.EXHAUSTED:
            raise AssertionError("successful one-time grant must be consumed")
