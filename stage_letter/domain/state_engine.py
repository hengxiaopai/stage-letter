"""Pure-domain live state reducer for Gate 1.5.

This module carries the accepted Gate 0B transition semantics into formal runtime
without importing experiments/* and without performing persistence. It converts
ordered durable LiveObservation facts into transition intents. Later Gate 1.5
slices own reconstruction and atomic LiveSession/LiveEvent persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .live import LiveEventCause, LiveObservation, LiveStatus, SessionOrigin


class EngineState(str, Enum):
    UNKNOWN = "UNKNOWN"
    BOOTSTRAP_LIVE_PENDING = "BOOTSTRAP_LIVE_PENDING"
    OFFLINE_CONFIRMED = "OFFLINE_CONFIRMED"
    LIVE_PENDING = "LIVE_PENDING"
    LIVE_CONFIRMED = "LIVE_CONFIRMED"
    OFFLINE_PENDING = "OFFLINE_PENDING"


class TransitionIntentType(str, Enum):
    OPEN_SESSION = "OPEN_SESSION"
    CLOSE_SESSION = "CLOSE_SESSION"


@dataclass(frozen=True)
class EngineConfig:
    live_confirmations_required: int = 2
    offline_confirmations_required: int = 2

    def __post_init__(self) -> None:
        if self.live_confirmations_required < 1:
            raise ValueError("live_confirmations_required must be >= 1")
        if self.offline_confirmations_required < 1:
            raise ValueError("offline_confirmations_required must be >= 1")


@dataclass(frozen=True)
class TransitionIntent:
    intent_type: TransitionIntentType
    occurred_at: datetime
    cause: LiveEventCause
    origin: SessionOrigin | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.intent_type is TransitionIntentType.OPEN_SESSION:
            if self.origin is None:
                raise ValueError("OPEN_SESSION intent requires origin")
            expected = (
                LiveEventCause.BOOTSTRAP_LIVE
                if self.origin is SessionOrigin.BOOTSTRAP_LIVE
                else LiveEventCause.TRANSITION
            )
            if self.cause is not expected:
                raise ValueError("OPEN_SESSION cause must match session origin")
        else:
            if self.origin is not None:
                raise ValueError("CLOSE_SESSION intent must not carry origin")
            if self.cause is not LiveEventCause.TRANSITION:
                raise ValueError("CLOSE_SESSION cause must be TRANSITION")
            if self.source_started_at is not None:
                raise ValueError("CLOSE_SESSION must not invent source_started_at")


@dataclass(frozen=True)
class EngineSnapshot:
    state: EngineState
    live_streak: int
    offline_streak: int
    seen_observation_ids: frozenset[str]
    observation_watermark: datetime | None
    session_open: bool


@dataclass(frozen=True)
class ProcessResult:
    accepted: bool
    duplicate: bool
    stale: bool
    previous_state: EngineState
    current_state: EngineState
    emitted_intents: tuple[TransitionIntent, ...]


class LiveStateReducer:
    """Deterministic reducer for one PlatformAccount.

    The reducer owns only state semantics. It does not allocate persistence IDs,
    write sessions/events, access repositories, call providers, or decide
    notification eligibility.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.state = EngineState.UNKNOWN
        self.live_streak = 0
        self.offline_streak = 0
        self.seen_observation_ids: set[str] = set()
        self.observation_watermark: datetime | None = None
        self.session_open = False

    def snapshot(self) -> EngineSnapshot:
        return EngineSnapshot(
            state=self.state,
            live_streak=self.live_streak,
            offline_streak=self.offline_streak,
            seen_observation_ids=frozenset(self.seen_observation_ids),
            observation_watermark=self.observation_watermark,
            session_open=self.session_open,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: EngineSnapshot,
        config: EngineConfig | None = None,
    ) -> "LiveStateReducer":
        reducer = cls(config=config)
        if snapshot.live_streak < 0 or snapshot.offline_streak < 0:
            raise ValueError("snapshot streaks must be non-negative")
        reducer.state = snapshot.state
        reducer.live_streak = snapshot.live_streak
        reducer.offline_streak = snapshot.offline_streak
        reducer.seen_observation_ids = set(snapshot.seen_observation_ids)
        reducer.observation_watermark = snapshot.observation_watermark
        reducer.session_open = snapshot.session_open
        reducer._assert_invariants()
        return reducer

    def process(self, observation: LiveObservation) -> ProcessResult:
        previous_state = self.state

        # Duplicate classification wins over stale classification, matching the
        # accepted Gate 0B oracle semantics.
        if observation.observation_id in self.seen_observation_ids:
            return ProcessResult(
                accepted=False,
                duplicate=True,
                stale=False,
                previous_state=previous_state,
                current_state=self.state,
                emitted_intents=(),
            )

        self.seen_observation_ids.add(observation.observation_id)

        if (
            self.observation_watermark is not None
            and observation.observed_at < self.observation_watermark
        ):
            self._assert_invariants()
            return ProcessResult(
                accepted=False,
                duplicate=False,
                stale=True,
                previous_state=previous_state,
                current_state=self.state,
                emitted_intents=(),
            )

        if (
            self.observation_watermark is None
            or observation.observed_at > self.observation_watermark
        ):
            self.observation_watermark = observation.observed_at

        # UNKNOWN is accepted evidence and advances ordering, but never advances
        # a decisive streak, opens/closes a session, or emits an event intent.
        if observation.status is LiveStatus.UNKNOWN:
            return ProcessResult(
                accepted=True,
                duplicate=False,
                stale=False,
                previous_state=previous_state,
                current_state=self.state,
                emitted_intents=(),
            )

        emitted: list[TransitionIntent] = []

        if self.state is EngineState.UNKNOWN:
            if observation.status is LiveStatus.OFFLINE:
                self._to_offline_confirmed()
            else:
                self.live_streak = 1
                if self.config.live_confirmations_required == 1:
                    emitted.append(self._confirm_live(observation, bootstrap=True))
                else:
                    self.state = EngineState.BOOTSTRAP_LIVE_PENDING

        elif self.state is EngineState.BOOTSTRAP_LIVE_PENDING:
            if observation.status is LiveStatus.LIVE:
                self.live_streak += 1
                if self.live_streak >= self.config.live_confirmations_required:
                    emitted.append(self._confirm_live(observation, bootstrap=True))
            else:
                self._to_offline_confirmed()

        elif self.state is EngineState.OFFLINE_CONFIRMED:
            if observation.status is LiveStatus.LIVE:
                self.live_streak = 1
                if self.config.live_confirmations_required == 1:
                    emitted.append(self._confirm_live(observation, bootstrap=False))
                else:
                    self.state = EngineState.LIVE_PENDING
            else:
                self.live_streak = 0

        elif self.state is EngineState.LIVE_PENDING:
            if observation.status is LiveStatus.LIVE:
                self.live_streak += 1
                if self.live_streak >= self.config.live_confirmations_required:
                    emitted.append(self._confirm_live(observation, bootstrap=False))
            else:
                self._to_offline_confirmed()

        elif self.state is EngineState.LIVE_CONFIRMED:
            if observation.status is LiveStatus.OFFLINE:
                self.offline_streak = 1
                if self.config.offline_confirmations_required == 1:
                    emitted.append(self._confirm_offline(observation))
                else:
                    self.state = EngineState.OFFLINE_PENDING
            else:
                self.offline_streak = 0

        elif self.state is EngineState.OFFLINE_PENDING:
            if observation.status is LiveStatus.OFFLINE:
                self.offline_streak += 1
                if self.offline_streak >= self.config.offline_confirmations_required:
                    emitted.append(self._confirm_offline(observation))
            else:
                self.state = EngineState.LIVE_CONFIRMED
                self.offline_streak = 0

        self._assert_invariants()
        return ProcessResult(
            accepted=True,
            duplicate=False,
            stale=False,
            previous_state=previous_state,
            current_state=self.state,
            emitted_intents=tuple(emitted),
        )

    def _to_offline_confirmed(self) -> None:
        self.state = EngineState.OFFLINE_CONFIRMED
        self.live_streak = 0
        self.offline_streak = 0

    def _confirm_live(self, observation: LiveObservation, *, bootstrap: bool) -> TransitionIntent:
        if self.session_open:
            raise AssertionError("attempted to open a duplicate live session")
        origin = SessionOrigin.BOOTSTRAP_LIVE if bootstrap else SessionOrigin.TRANSITION
        cause = LiveEventCause.BOOTSTRAP_LIVE if bootstrap else LiveEventCause.TRANSITION
        self.session_open = True
        self.state = EngineState.LIVE_CONFIRMED
        self.live_streak = 0
        self.offline_streak = 0
        return TransitionIntent(
            intent_type=TransitionIntentType.OPEN_SESSION,
            occurred_at=observation.observed_at,
            origin=origin,
            cause=cause,
            source_started_at=observation.source_started_at,
        )

    def _confirm_offline(self, observation: LiveObservation) -> TransitionIntent:
        if not self.session_open:
            raise AssertionError("attempted to close a missing live session")
        self.session_open = False
        self._to_offline_confirmed()
        return TransitionIntent(
            intent_type=TransitionIntentType.CLOSE_SESSION,
            occurred_at=observation.observed_at,
            cause=LiveEventCause.TRANSITION,
        )

    def _assert_invariants(self) -> None:
        live_state = self.state in (EngineState.LIVE_CONFIRMED, EngineState.OFFLINE_PENDING)
        if live_state != self.session_open:
            raise AssertionError("engine state/session-open invariant violated")
