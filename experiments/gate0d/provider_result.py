#!/usr/bin/env python3
"""Gate 0D-2 — provider/grant result normalization.

This module is deliberately independent from raw WeChat errcode values.
A provider adapter must first classify a concrete provider response into one of
``ProviderOutcome`` values. This layer then freezes retry class, terminality,
and grant mutation semantics in a deterministic provider-agnostic form.

Raw WeChat errcode mapping belongs to the real-provider evidence boundary and
must be based on current official documentation / observed responses rather
than guessed in this Gate experiment.

Important real-provider correction (Gate 0D-4, 2026-08-18): a successful
subscription-message send was followed by another successful real send for the
same account without an intervening subscription request in the controlled
sequence. Therefore ``SENT`` proves that one send unit was consumed, but does
*not* prove that no additional send entitlement remains. This experiment does
not maintain an exact provider-side grant balance, so successful send must not
silently rewrite ``GRANTED`` to ``EXHAUSTED``. Only explicit exhaustion evidence
may do that.

No type in this module can mutate creator LIVE/OFFLINE state or LiveSession.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from notification_truth import GrantState


class ProviderOutcome(str, Enum):
    SENT = "SENT"
    USER_REJECTED = "USER_REJECTED"
    GRANT_INVALID = "GRANT_INVALID"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TEMPLATE_INVALID = "TEMPLATE_INVALID"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class RetryClass(str, Enum):
    NONE = "NONE"
    TRANSIENT = "TRANSIENT"
    AFTER_AUTH = "AFTER_AUTH"
    AFTER_COOLDOWN = "AFTER_COOLDOWN"
    AFTER_CONFIG_FIX = "AFTER_CONFIG_FIX"


class GrantEffect(str, Enum):
    KEEP = "KEEP"
    CONSUME_ONE = "CONSUME_ONE"
    MARK_DENIED = "MARK_DENIED"
    MARK_EXHAUSTED = "MARK_EXHAUSTED"


@dataclass(frozen=True)
class ProviderResult:
    outcome: ProviderOutcome
    provider_code: str | None = None
    provider_message: str | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be >= 0")


@dataclass(frozen=True)
class NormalizedProviderResult:
    outcome: ProviderOutcome
    success: bool
    terminal_for_delivery: bool
    retryable: bool
    retry_class: RetryClass
    grant_effect: GrantEffect
    provider_code: str | None
    provider_message: str | None
    retry_after_seconds: int | None


_OUTCOME_POLICY: dict[
    ProviderOutcome,
    tuple[bool, bool, bool, RetryClass, GrantEffect],
] = {
    ProviderOutcome.SENT: (
        True,
        True,
        False,
        RetryClass.NONE,
        GrantEffect.CONSUME_ONE,
    ),
    ProviderOutcome.USER_REJECTED: (
        False,
        True,
        False,
        RetryClass.NONE,
        GrantEffect.MARK_DENIED,
    ),
    ProviderOutcome.GRANT_INVALID: (
        False,
        True,
        False,
        RetryClass.NONE,
        GrantEffect.MARK_EXHAUSTED,
    ),
    ProviderOutcome.AUTH_REQUIRED: (
        False,
        False,
        True,
        RetryClass.AFTER_AUTH,
        GrantEffect.KEEP,
    ),
    ProviderOutcome.TEMPLATE_INVALID: (
        False,
        False,
        False,
        RetryClass.AFTER_CONFIG_FIX,
        GrantEffect.KEEP,
    ),
    ProviderOutcome.RATE_LIMITED: (
        False,
        False,
        True,
        RetryClass.AFTER_COOLDOWN,
        GrantEffect.KEEP,
    ),
    ProviderOutcome.NETWORK_ERROR: (
        False,
        False,
        True,
        RetryClass.TRANSIENT,
        GrantEffect.KEEP,
    ),
    ProviderOutcome.PROVIDER_ERROR: (
        False,
        False,
        True,
        RetryClass.TRANSIENT,
        GrantEffect.KEEP,
    ),
}


def normalize_provider_result(result: ProviderResult) -> NormalizedProviderResult:
    success, terminal, retryable, retry_class, grant_effect = _OUTCOME_POLICY[result.outcome]

    if result.outcome is ProviderOutcome.SENT and result.retry_after_seconds is not None:
        raise ValueError("SENT cannot carry retry_after_seconds")

    if result.outcome in (
        ProviderOutcome.USER_REJECTED,
        ProviderOutcome.GRANT_INVALID,
        ProviderOutcome.TEMPLATE_INVALID,
    ) and result.retry_after_seconds is not None:
        raise ValueError(f"{result.outcome.value} cannot carry retry_after_seconds")

    return NormalizedProviderResult(
        outcome=result.outcome,
        success=success,
        terminal_for_delivery=terminal,
        retryable=retryable,
        retry_class=retry_class,
        grant_effect=grant_effect,
        provider_code=result.provider_code,
        provider_message=result.provider_message,
        retry_after_seconds=result.retry_after_seconds,
    )


def apply_grant_effect(
    current: GrantState,
    normalized: NormalizedProviderResult,
) -> GrantState:
    """Apply provider/grant truth without inventing an exact grant balance.

    ``CONSUME_ONE`` records that one provider-side send entitlement was used.
    The current experiment has no authoritative remaining-balance counter, so a
    successful send does not by itself prove ``EXHAUSTED``. Explicit provider
    evidence classified as ``GRANT_INVALID`` remains the boundary that can mark
    the locally modeled grant state exhausted.
    """

    effect = normalized.grant_effect
    if effect in (GrantEffect.KEEP, GrantEffect.CONSUME_ONE):
        return current
    if effect is GrantEffect.MARK_DENIED:
        return GrantState.DENIED
    if effect is GrantEffect.MARK_EXHAUSTED:
        return GrantState.EXHAUSTED
    raise AssertionError(f"unhandled grant effect: {effect}")
