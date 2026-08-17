#!/usr/bin/env python3
"""Stage Letter Gate 0B — minimal pure-domain state engine.

This module intentionally has no database, queue, HTTP, Redis, WeChat, or
provider dependency. Gate 0B validates only the domain semantics between
normalized LiveObservation input and LiveSession / LiveEvent output.

Frozen safety rules:
- UNKNOWN != OFFLINE.
- UNKNOWN never closes a LiveSession.
- only explicit LIVE/OFFLINE observations may advance decisive transitions.
- repeated observations must not duplicate sessions or events.
- at most one LiveSession may be open for one engine/account.

Current Gate 0B-1 bootstrap policy preserves the previously frozen chain:
UNKNOWN -> OFFLINE_CONFIRMED before a LIVE transition may be confirmed.
A creator first observed while already LIVE therefore remains UNKNOWN until an
explicit OFFLINE baseline exists. That bootstrap limitation is deliberate and
must be revisited explicitly rather than changed silently.
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
    OFFLINE_CONFIRMED = "OFFLINE_CONFIRMED"
    LIVE_PENDING = "LIVE_PENDING"
    LIVE_CONFIRMED = "LIVE_CONFIRMED"
    OFFLINE_PENDING = "OFFLINE_PENDING"


class LiveEventType(str, Enum):
    LIVE_STARTED = "LIVE_STARTED"
    LIVE_ENDED = "LIVE_ENDED"


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


@dataclass
class LiveSession:
    session_id: int
    opened_at: datetime
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True)
class LiveEvent:
    event_type: LiveEventType
    session_id: int
    occurred_at: datetime


@dataclass(frozen=True)
class ProcessResult:
    accepted: bool
    duplicate: bool
    previous_state: EngineState
    current_state: EngineState
    emitted_events: tuple[LiveEvent, ...]


class StateEngine:
    """In-memory Gate engine for one PlatformAccount.

    The engine is intentionally deterministic and side-effect free except for
    its own in-memory state. Persistence/transactions belong to later Gate 0B
    steps.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.state = EngineState.UNKNOWN
        self.live_streak = 0
        self.offline_streak = 0
        self.sessions: list[LiveSession] = []
        self.events: list[LiveEvent] = []
        self._seen_observation_ids: set[str] = set()
        self._next_session_id = 1

    @property
    def open_session(self) -> LiveSession | None:
        open_sessions = [session for session in self.sessions if session.is_open]
        if len(open_sessions) > 1:
            raise AssertionError("invariant violated: more than one open LiveSession")
        return open_sessions[0] if open_sessions else None

    def process_many(self, observations: Iterable[LiveObservation]) -> list[ProcessResult]:
        return [self.process(observation) for observation in observations]

    def process(self, observation: LiveObservation) -> ProcessResult:
        previous_state = self.state

        if observation.observation_id in self._seen_observation_ids:
            return ProcessResult(
                accepted=False,
                duplicate=True,
                previous_state=previous_state,
                current_state=self.state,
                emitted_events=(),
            )

        self._seen_observation_ids.add(observation.observation_id)
        emitted: list[LiveEvent] = []

        if observation.status is ObservationStatus.UNKNOWN:
            # UNKNOWN is deliberately a pause/no-op. It neither advances nor
            # cancels a pending decisive transition and never closes a session.
            return ProcessResult(
                accepted=True,
                duplicate=False,
                previous_state=previous_state,
                current_state=self.state,
                emitted_events=(),
            )

        if self.state is EngineState.UNKNOWN:
            if observation.status is ObservationStatus.OFFLINE:
                self.state = EngineState.OFFLINE_CONFIRMED
                self.live_streak = 0
                self.offline_streak = 0
            # Frozen Gate 0B-1 bootstrap rule: initial LIVE does not create a
            # session before an explicit OFFLINE baseline exists.

        elif self.state is EngineState.OFFLINE_CONFIRMED:
            if observation.status is ObservationStatus.LIVE:
                self.live_streak = 1
                self.state = EngineState.LIVE_PENDING
            else:
                self.live_streak = 0

        elif self.state is EngineState.LIVE_PENDING:
            if observation.status is ObservationStatus.LIVE:
                self.live_streak += 1
                if self.live_streak >= self.config.live_confirmations_required:
                    session = self._open_session(observation.observed_at)
                    event = LiveEvent(
                        event_type=LiveEventType.LIVE_STARTED,
                        session_id=session.session_id,
                        occurred_at=observation.observed_at,
                    )
                    self.events.append(event)
                    emitted.append(event)
                    self.state = EngineState.LIVE_CONFIRMED
                    self.live_streak = 0
                    self.offline_streak = 0
            else:
                # Explicit opposite evidence cancels pending LIVE.
                self.state = EngineState.OFFLINE_CONFIRMED
                self.live_streak = 0

        elif self.state is EngineState.LIVE_CONFIRMED:
            if observation.status is ObservationStatus.OFFLINE:
                self.offline_streak = 1
                self.state = EngineState.OFFLINE_PENDING
            else:
                self.offline_streak = 0

        elif self.state is EngineState.OFFLINE_PENDING:
            if observation.status is ObservationStatus.OFFLINE:
                self.offline_streak += 1
                if self.offline_streak >= self.config.offline_confirmations_required:
                    session = self._close_open_session(observation.observed_at)
                    event = LiveEvent(
                        event_type=LiveEventType.LIVE_ENDED,
                        session_id=session.session_id,
                        occurred_at=observation.observed_at,
                    )
                    self.events.append(event)
                    emitted.append(event)
                    self.state = EngineState.OFFLINE_CONFIRMED
                    self.offline_streak = 0
                    self.live_streak = 0
            else:
                # Explicit opposite evidence cancels pending OFFLINE and keeps
                # the existing session open.
                self.state = EngineState.LIVE_CONFIRMED
                self.offline_streak = 0

        self._assert_invariants()
        return ProcessResult(
            accepted=True,
            duplicate=False,
            previous_state=previous_state,
            current_state=self.state,
            emitted_events=tuple(emitted),
        )

    def _open_session(self, opened_at: datetime) -> LiveSession:
        if self.open_session is not None:
            raise AssertionError("invariant violated: attempted duplicate open LiveSession")
        session = LiveSession(session_id=self._next_session_id, opened_at=opened_at)
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
