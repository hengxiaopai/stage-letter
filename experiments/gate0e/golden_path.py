#!/usr/bin/env python3
"""Gate 0E — end-to-end golden-path composition harness.

This experiment composes the already-proven Gate 0B/0C/0D boundaries without
creating a second implementation of their semantics:

SourceObservation
  -> SourceComposer
  -> canonical LiveObservation
  -> PersistentStateEngine
  -> LiveEvent
  -> notification eligibility
  -> logical NotificationDelivery
  -> DeliveryRetryMachine
  -> normalized provider result

The harness is intentionally provider-agnostic. Gate 0D already proved real
WeChat send/receipt behavior and the no-provider-dedupe safety boundary. Gate
0E proves that the Stage Letter domain pipeline hands exactly one eligible
OFFLINE -> LIVE transition into that delivery runtime while preserving UNKNOWN,
bootstrap-live, restart and duplicate safety.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "experiments/gate0b",
    "experiments/gate0c",
    "experiments/gate0d",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from state_engine import (  # noqa: E402
    EngineConfig,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    ObservationStatus,
    ProcessResult,
)
from sqlite_store import PersistentStateEngine  # noqa: E402
from platform_health import CanonicalStatus, HealthState  # noqa: E402
from source_composition import (  # noqa: E402
    ComposedObservation,
    IngestResult,
    SourceComposer,
    SourceCompositionPolicy,
    SourceObservation,
    SourceRole,
)
from notification_truth import (  # noqa: E402
    DeliveryCreateResult,
    DeliveryKey,
    DeliveryLedger,
    EligibilityDecision,
    EventCause,
    EventType,
    GrantState,
    NotificationDelivery,
    NotificationEvent,
    NotificationTarget,
    evaluate_eligibility,
)
from delivery_retry import (  # noqa: E402
    CompleteAttemptResult,
    DeliveryRetryMachine,
    ExecutionState,
)
from provider_result import (  # noqa: E402
    ProviderOutcome,
    ProviderResult,
    normalize_provider_result,
)


@dataclass(frozen=True)
class GoldenTarget:
    user_id: str
    following: bool = True
    notification_enabled: bool = True
    grant_state: GrantState = GrantState.GRANTED


@dataclass(frozen=True)
class NotificationContext:
    event_id: str
    account_id: str
    session_id: str
    occurred_at: datetime
    title: str | None
    live_url: str | None
    source_started_at: datetime | None


@dataclass(frozen=True)
class GoldenStepResult:
    source_ingest: IngestResult
    composed: ComposedObservation
    state_result: ProcessResult | None
    notification_events: tuple[NotificationEvent, ...]
    eligibility: tuple[EligibilityDecision, ...]
    deliveries: tuple[DeliveryCreateResult, ...]


def default_source_policy() -> SourceCompositionPolicy:
    return SourceCompositionPolicy(
        primary_source="streamget",
        roles={
            "streamget": SourceRole.PRIMARY_STATUS,
            "tikhub": SourceRole.POSITIVE_STATUS,
            "f2": SourceRole.POSITIVE_STATUS,
        },
        metadata_priority=("tikhub", "f2", "streamget"),
        max_fallback_lag_seconds=120,
        conflict_window_seconds=120,
        max_metadata_lag_seconds=300,
    )


def bridge_status(status: CanonicalStatus) -> ObservationStatus:
    return ObservationStatus(status.value)


def event_id(account_id: str, event_type: LiveEventType, session_id: int) -> str:
    return f"{account_id}:{event_type.value}:{session_id}"


class GoldenPathHarness:
    """Minimal integration runtime for one account and one notification target."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        account_id: str,
        target: GoldenTarget,
        engine_config: EngineConfig | None = None,
        source_policy: SourceCompositionPolicy | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        if not target.user_id:
            raise ValueError("target user_id is required")

        self.account_id = account_id
        self.target = target
        self.composer = SourceComposer(account_id, source_policy or default_source_policy())
        self.state_store = PersistentStateEngine(
            db_path,
            account_id,
            engine_config or EngineConfig(
                live_confirmations_required=2,
                offline_confirmations_required=2,
            ),
        )
        self.ledger = DeliveryLedger()
        self.runtimes: dict[DeliveryKey, DeliveryRetryMachine] = {}
        self.contexts: dict[str, NotificationContext] = {}

    def process_source(self, observation: SourceObservation) -> GoldenStepResult:
        ingest = self.composer.ingest(observation)
        composed = self.composer.compose()

        if ingest.duplicate or ingest.stale or composed.observed_at is None:
            return GoldenStepResult(ingest, composed, None, (), (), ())

        canonical = LiveObservation(
            observation_id=f"composed:{observation.source_id}:{observation.observation_id}",
            status=bridge_status(composed.status),
            observed_at=composed.observed_at,
            source="+".join(composed.status_sources) or composed.reason.value,
            source_started_at=composed.source_started_at,
        )
        state_result = self.state_store.process(canonical)

        notification_events: list[NotificationEvent] = []
        decisions: list[EligibilityDecision] = []
        deliveries: list[DeliveryCreateResult] = []

        for domain_event in state_result.emitted_events:
            notification_event = self._bridge_event(domain_event)
            notification_events.append(notification_event)
            target = NotificationTarget(
                user_id=self.target.user_id,
                account_id=self.account_id,
                following=self.target.following,
                notification_enabled=self.target.notification_enabled,
                grant_state=self.target.grant_state,
            )
            decision = evaluate_eligibility(notification_event, target)
            decisions.append(decision)
            created = self.ledger.create_if_eligible(decision, notification_event, target)
            deliveries.append(created)

            if created.delivery is not None:
                self.contexts[notification_event.event_id] = NotificationContext(
                    event_id=notification_event.event_id,
                    account_id=self.account_id,
                    session_id=notification_event.session_id,
                    occurred_at=notification_event.occurred_at,
                    title=composed.title,
                    live_url=composed.live_url,
                    source_started_at=composed.source_started_at,
                )

            if created.created and created.delivery is not None:
                self.runtimes[created.delivery.key] = DeliveryRetryMachine.from_delivery(
                    created.delivery,
                    grant_state=self.target.grant_state,
                )

        return GoldenStepResult(
            source_ingest=ingest,
            composed=composed,
            state_result=state_result,
            notification_events=tuple(notification_events),
            eligibility=tuple(decisions),
            deliveries=tuple(deliveries),
        )

    def apply_provider_result(
        self,
        key: DeliveryKey,
        *,
        outcome: ProviderOutcome,
        started_at: datetime,
        completed_at: datetime,
        provider_code: str | None = None,
        provider_message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> CompleteAttemptResult:
        runtime = self.runtimes[key]
        attempt_id = f"{key.live_event_id}:attempt:{runtime.attempt_count + 1}"
        begin = runtime.begin_attempt(attempt_id=attempt_id, started_at=started_at)
        if not begin.started or begin.attempt is None:
            raise ValueError(f"delivery is not eligible to begin another attempt: {runtime.state.value}")

        normalized = normalize_provider_result(
            ProviderResult(
                outcome=outcome,
                provider_code=provider_code,
                provider_message=provider_message,
                retry_after_seconds=retry_after_seconds,
            )
        )
        return runtime.complete_attempt(
            attempt_id=attempt_id,
            result=normalized,
            completed_at=completed_at,
        )

    def _bridge_event(self, domain_event) -> NotificationEvent:
        bridged_type = EventType(domain_event.event_type.value)
        bridged_cause = EventCause(domain_event.cause.value)
        return NotificationEvent(
            event_id=event_id(self.account_id, domain_event.event_type, domain_event.session_id),
            account_id=self.account_id,
            event_type=bridged_type,
            cause=bridged_cause,
            occurred_at=domain_event.occurred_at,
            session_id=str(domain_event.session_id),
        )

    def runtime_for(self, delivery: NotificationDelivery) -> DeliveryRetryMachine:
        return self.runtimes[delivery.key]

    def context_for_event(self, notification_event_id: str) -> NotificationContext | None:
        return self.contexts.get(notification_event_id)

    @property
    def live_snapshot(self):
        return self.state_store.snapshot()

    @property
    def delivery_count(self) -> int:
        return self.ledger.count


__all__ = [
    "CanonicalStatus",
    "DeliveryRetryMachine",
    "EngineConfig",
    "ExecutionState",
    "GoldenPathHarness",
    "GoldenStepResult",
    "GoldenTarget",
    "GrantState",
    "HealthState",
    "NotificationContext",
    "ProviderOutcome",
    "SourceObservation",
]
