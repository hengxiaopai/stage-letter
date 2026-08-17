#!/usr/bin/env python3
"""Stage Letter Gate 0B — pure-domain live state engine.

Gate 0B-3 adds two production-critical semantics on top of the already proven
Gate 0B-1/0B-2 behavior:

1. A creator first observed while already LIVE may be adopted after repeated
   decisive LIVE observations. The resulting session is explicitly marked as
   BOOTSTRAP_LIVE so downstream notification logic can distinguish discovery
   from a real OFFLINE -> LIVE transition.
2. A per-account observation watermark rejects out-of-order older facts. Stale
   observations are durably idempotent evidence but never change state, streaks,
   sessions, events, or the watermark.

Frozen safety rules remain:
- UNKNOWN != OFFLINE.
- UNKNOWN never closes a LiveSession.
- only explicit LIVE/OFFLINE observations advance decisive transitions.
- repeated observation ids do not duplicate sessions or events.
- at most one LiveSession may be open for one engine/account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable


class ObservationStatus(str, Enum):
    LIVE = "LIVE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class EngineState(str, Enum):
    UNKNOWN = "UNKNOWN"
    BOOTSTRAP_LIVE_PENDING = "BOOTSTRAP_LIVE_PENDING"
    OFFLINE_CONFIRMED = "OFFLINE_CONFIRMED"
    LIVE_PENDING = "LIVE_PENDING"
    LIVE_CONFIRMED = "LIVE_CONFIRMED"
    OFFLINE_PENDING = "OFFLINE_PENDING"


class SessionOrigin(str, Enum):
    TRANSITION = "TRANSITION"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"


class LiveEventType(str, Enum):
    LIVE_STARTED = "LIVE_STARTED"
    LIVE_ENDED = "LIVE_ENDED"


class LiveEventCause(str, Enum):
    TRANSITION = "TRANSITION"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"


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
class LiveObservation:
    observation_id: str
    status: ObservationStatus
    observed_at: datetime
    source: str = "test"
    source_started_at: datetime | None = None


@dataclass
class LiveSession:
    session_id: int
    opened_at: datetime
    closed_at: datetime | None = None
    origin: SessionOrigin = SessionOrigin.TRANSITION
    source_started_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True)
class LiveEvent:
    event_type: LiveEventType
    session_id: int
    occurred_at: datetime
    cause: LiveEventCause = LiveEventCause.TRANSITION


@dataclass(frozen=True)
class LiveSessionSnapshot:
    session_id: int
    opened_at: datetime
    closed_at: datetime | None
    origin: SessionOrigin = SessionOrigin.TRANSITION
    source_started_at: datetime | None = None


@dataclass(frozen=True)
class EngineSnapshot:
    state: EngineState
    live_streak: int
    offline_streak: int
    sessions: tuple[LiveSessionSnapshot, ...]
    events: tuple[LiveEvent, ...]
    seen_observation_ids: frozenset[str]
    next_session_id: int
    observation_watermark: datetime | None = None


@dataclass(frozen=True)
class ProcessResult:
    accepted: bool
    duplicate: bool
    stale: bool
    previous_state: EngineState
    current_state: EngineState
    emitted_events: tuple[LiveEvent, ...]


class StateEngine:
    """Deterministic domain engine for one PlatformAccount."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.state = EngineState.UNKNOWN
        self.live_streak = 0
        self.offline_streak = 0
        self.sessions: list[LiveSession] = []
        self.events: list[LiveEvent] = []
        self._seen_observation_ids: set[str] = set()
        self._next_session_id = 1
        self.observation_watermark: datetime | None = None

    @property
    def open_session(self) -> LiveSession | None:
        open_sessions = [session for session in self.sessions if session.is_open]
        if len(open_sessions) > 1:
            raise AssertionError("invariant violated: more than one open LiveSession")
        return open_sessions[0] if open_sessions else None

    def snapshot(self) -> EngineSnapshot:
        return EngineSnapshot(
            state=self.state,
            live_streak=self.live_streak,
            offline_streak=self.offline_streak,
            sessions=tuple(
                LiveSessionSnapshot(
                    session_id=session.session_id,
                    opened_at=session.opened_at,
                    closed_at=session.closed_at,
                    origin=session.origin,
                    source_started_at=session.source_started_at,
                )
                for session in self.sessions
            ),
            events=tuple(self.events),
            seen_observation_ids=frozenset(self._seen_observation_ids),
            next_session_id=self._next_session_id,
            observation_watermark=self.observation_watermark,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: EngineSnapshot,
        config: EngineConfig | None = None,
    ) -> StateEngine:
        engine = cls(config=config)
        engine.state = snapshot.state
        engine.live_streak = snapshot.live_streak
        engine.offline_streak = snapshot.offline_streak
        engine.sessions = [
            LiveSession(
                session_id=session.session_id,
                opened_at=session.opened_at,
                closed_at=session.closed_at,
                origin=session.origin,
                source_started_at=session.source_started_at,
            )
            for session in snapshot.sessions
        ]
        engine.events = list(snapshot.events)
        engine._seen_observation_ids = set(snapshot.seen_observation_ids)
        engine._next_session_id = snapshot.next_session_id
        engine.observation_watermark = snapshot.observation_watermark

        max_session_id = max((session.session_id for session in engine.sessions), default=0)
        if engine._next_session_id <= max_session_id:
            raise ValueError("snapshot next_session_id must be greater than existing session ids")
        if engine.live_streak < 0 or engine.offline_streak < 0:
            raise ValueError("snapshot streaks must be non-negative")

        engine._assert_invariants()
        return engine

    def process_many(self, observations: Iterable[LiveObservation]) -> list[ProcessResult]:
        return [self.process(observation) for observation in observations]

    def process(self, observation: LiveObservation) -> ProcessResult:
        previous_state = self.state

        # Idempotency wins over ordering classification: replaying a known id is
        # a duplicate even if its timestamp is older than the current watermark.
        if observation.observation_id in self._seen_observation_ids:
            return ProcessResult(
                accepted=False,
                duplicate=True,
                stale=False,
                previous_state=previous_state,
                current_state=self.state,
                emitted_events=(),
            )

        self._seen_observation_ids.add(observation.observation_id)

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
                emitted_events=(),
            )

        if (
            self.observation_watermark is None
            or observation.observed_at > self.observation_watermark
        ):
            self.observation_watermark = observation.observed_at

        emitted: list[LiveEvent] = []

        if observation.status is ObservationStatus.UNKNOWN:
            # UNKNOWN advances the ordering watermark because it is a newer
            # observation, but it never changes decisive live state.
            return ProcessResult(
                accepted=True,
                duplicate=False,
                stale=False,
                previous_state=previous_state,
                current_state=self.state,
                emitted_events=(),
            )

        if self.state is EngineState.UNKNOWN:
            if observation.status is ObservationStatus.OFFLINE:
                self._to_offline_confirmed()
            else:
                self.live_streak = 1
                if self.config.live_confirmations_required == 1:
                    emitted.append(
                        self._confirm_live(
                            observation,
                            origin=SessionOrigin.BOOTSTRAP_LIVE,
                            cause=LiveEventCause.BOOTSTRAP_LIVE,
                        )
                    )
                else:
                    self.state = EngineState.BOOTSTRAP_LIVE_PENDING

        elif self.state is EngineState.BOOTSTRAP_LIVE_PENDING:
            if observation.status is ObservationStatus.LIVE:
                self.live_streak += 1
                if self.live_streak >= self.config.live_confirmations_required:
                    emitted.append(
                        self._confirm_live(
                            observation,
                            origin=SessionOrigin.BOOTSTRAP_LIVE,
                            cause=LiveEventCause.BOOTSTRAP_LIVE,
                        )
                    )
            else:
                # Explicit OFFLINE proves there was no stable bootstrap LIVE.
                self._to_offline_confirmed()

        elif self.state is EngineState.OFFLINE_CONFIRMED:
            if observation.status is ObservationStatus.LIVE:
                self.live_streak = 1
                if self.config.live_confirmations_required == 1:
                    emitted.append(
                        self._confirm_live(
                            observation,
                            origin=SessionOrigin.TRANSITION,
                            cause=LiveEventCause.TRANSITION,
                        )
                    )
                else:
                    self.state = EngineState.LIVE_PENDING
            else:
                self.live_streak = 0

        elif self.state is EngineState.LIVE_PENDING:
            if observation.status is ObservationStatus.LIVE:
                self.live_streak += 1
                if self.live_streak >= self.config.live_confirmations_required:
                    emitted.append(
                        self._confirm_live(
                            observation,
                            origin=SessionOrigin.TRANSITION,
                            cause=LiveEventCause.TRANSITION,
                        )
                    )
            else:
                self._to_offline_confirmed()

        elif self.state is EngineState.LIVE_CONFIRMED:
            if observation.status is ObservationStatus.OFFLINE:
                self.offline_streak = 1
                if self.config.offline_confirmations_required == 1:
                    emitted.append(self._confirm_offline(observation))
                else:
                    self.state = EngineState.OFFLINE_PENDING
            else:
                self.offline_streak = 0

        elif self.state is EngineState.OFFLINE_PENDING:
            if observation.status is ObservationStatus.OFFLINE:
                self.offline_streak += 1
                if self.offline_streak >= self.config.offline_confirmations_required:
                    emitted.append(self._confirm_offline(observation))
            else:
                # Explicit LIVE cancels pending close and keeps the session open.
                self.state = EngineState.LIVE_CONFIRMED
                self.offline_streak = 0

        self._assert_invariants()
        return ProcessResult(
            accepted=True,
            duplicate=False,
            stale=False,
            previous_state=previous_state,
            current_state=self.state,
            emitted_events=tuple(emitted),
        )

    def _to_offline_confirmed(self) -> None:
        self.state = EngineState.OFFLINE_CONFIRMED
        self.live_streak = 0
        self.offline_streak = 0

    def _confirm_live(
        self,
        observation: LiveObservation,
        *,
        origin: SessionOrigin,
        cause: LiveEventCause,
    ) -> LiveEvent:
        session = self._open_session(
            opened_at=observation.observed_at,
            origin=origin,
            source_started_at=observation.source_started_at,
        )
        event = LiveEvent(
            event_type=LiveEventType.LIVE_STARTED,
            session_id=session.session_id,
            occurred_at=observation.observed_at,
            cause=cause,
        )
        self.events.append(event)
        self.state = EngineState.LIVE_CONFIRMED
        self.live_streak = 0
        self.offline_streak = 0
        return event

    def _confirm_offline(self, observation: LiveObservation) -> LiveEvent:
        session = self._close_open_session(observation.observed_at)
        event = LiveEvent(
            event_type=LiveEventType.LIVE_ENDED,
            session_id=session.session_id,
            occurred_at=observation.observed_at,
            cause=LiveEventCause.TRANSITION,
        )
        self.events.append(event)
        self._to_offline_confirmed()
        return event

    def _open_session(
        self,
        opened_at: datetime,
        *,
        origin: SessionOrigin,
        source_started_at: datetime | None,
    ) -> LiveSession:
        if self.open_session is not None:
            raise AssertionError("invariant violated: attempted duplicate open LiveSession")
        session = LiveSession(
            session_id=self._next_session_id,
            opened_at=opened_at,
            origin=origin,
            source_started_at=source_started_at,
        )
        self._next_session_id += 1
        self.sessions.append(session)
        return session

    def _close_open_session(self, closed_at: datetime) -> LiveSession:
        session = self.open_session
        if session is None:
            raise AssertionError("invariant violated: no open LiveSession to close")
        session.closed_at = closed_at
        return session

    def _assert_invariants(self) -> None:
        open_session = self.open_session
        if self.state in (EngineState.LIVE_CONFIRMED, EngineState.OFFLINE_PENDING):
            if open_session is None:
                raise AssertionError("live state requires exactly one open LiveSession")
        else:
            if open_session is not None:
                raise AssertionError("non-live state must not retain an open LiveSession")

        starts = [event for event in self.events if event.event_type is LiveEventType.LIVE_STARTED]
        ends = [event for event in self.events if event.event_type is LiveEventType.LIVE_ENDED]
        if len(starts) < len(ends):
            raise AssertionError("cannot emit more LIVE_ENDED events than LIVE_STARTED events")
        if len(starts) != len(self.sessions):
            raise AssertionError("every canonical LiveSession must have exactly one LIVE_STARTED event")

        sessions_by_id = {session.session_id: session for session in self.sessions}
        for event in starts:
            session = sessions_by_id.get(event.session_id)
            if session is None:
                raise AssertionError("LIVE_STARTED must reference an existing session")
            expected_cause = (
                LiveEventCause.BOOTSTRAP_LIVE
                if session.origin is SessionOrigin.BOOTSTRAP_LIVE
                else LiveEventCause.TRANSITION
            )
            if event.cause is not expected_cause:
                raise AssertionError("LIVE_STARTED cause must match LiveSession origin")
