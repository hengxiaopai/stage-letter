#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from state_engine import (
    EngineConfig,
    EngineState,
    LiveEventType,
    LiveObservation,
    ObservationStatus,
    StateEngine,
)

UTC = timezone.utc
BASE = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)


def obs(index: int, status: ObservationStatus, observation_id: str | None = None) -> LiveObservation:
    return LiveObservation(
        observation_id=observation_id or f"obs-{index}",
        status=status,
        observed_at=BASE + timedelta(seconds=index),
        source="gate0b-test",
    )


class StateEngineGate0BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StateEngine(
            EngineConfig(live_confirmations_required=2, offline_confirmations_required=2)
        )

    def bootstrap_offline(self) -> None:
        self.engine.process(obs(1, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)

    def confirm_live(self, start: int = 2) -> None:
        self.engine.process(obs(start, ObservationStatus.LIVE))
        self.engine.process(obs(start + 1, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_CONFIRMED)

    def test_unknown_is_not_offline_and_does_not_bootstrap(self) -> None:
        result = self.engine.process(obs(1, ObservationStatus.UNKNOWN))
        self.assertEqual(result.current_state, EngineState.UNKNOWN)
        self.assertEqual(self.engine.sessions, [])
        self.assertEqual(self.engine.events, [])

    def test_initial_live_does_not_bypass_frozen_offline_baseline(self) -> None:
        self.engine.process(obs(1, ObservationStatus.LIVE))
        self.engine.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.UNKNOWN)
        self.assertEqual(len(self.engine.sessions), 0)

    def test_explicit_offline_bootstraps_offline_confirmed(self) -> None:
        self.bootstrap_offline()
        self.assertIsNone(self.engine.open_session)

    def test_live_requires_two_confirmations_before_session_open(self) -> None:
        self.bootstrap_offline()
        self.engine.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.assertIsNone(self.engine.open_session)

        result = self.engine.process(obs(3, ObservationStatus.LIVE))
        self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertIsNotNone(self.engine.open_session)
        self.assertEqual(len(self.engine.sessions), 1)
        self.assertEqual([e.event_type for e in result.emitted_events], [LiveEventType.LIVE_STARTED])

    def test_pending_live_is_cancelled_by_explicit_offline(self) -> None:
        self.bootstrap_offline()
        self.engine.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.engine.process(obs(3, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(len(self.engine.sessions), 0)

    def test_unknown_pauses_pending_live_without_advancing_or_cancelling(self) -> None:
        self.bootstrap_offline()
        self.engine.process(obs(2, ObservationStatus.LIVE))
        self.engine.process(obs(3, ObservationStatus.UNKNOWN))
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.assertEqual(len(self.engine.sessions), 0)
        self.engine.process(obs(4, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(len(self.engine.sessions), 1)

    def test_repeated_live_after_confirmation_does_not_duplicate_session_or_event(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        for index in range(4, 9):
            self.engine.process(obs(index, ObservationStatus.LIVE))
        self.assertEqual(len(self.engine.sessions), 1)
        self.assertEqual(
            [e.event_type for e in self.engine.events],
            [LiveEventType.LIVE_STARTED],
        )

    def test_offline_requires_two_confirmations_before_closing_same_session(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        session = self.engine.open_session
        assert session is not None

        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_PENDING)
        self.assertTrue(session.is_open)

        result = self.engine.process(obs(5, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)
        self.assertFalse(session.is_open)
        self.assertEqual(len(self.engine.sessions), 1)
        self.assertEqual(result.emitted_events[0].event_type, LiveEventType.LIVE_ENDED)
        self.assertEqual(result.emitted_events[0].session_id, session.session_id)

    def test_unknown_during_offline_pending_never_closes_session(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        session = self.engine.open_session
        assert session is not None

        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.engine.process(obs(5, ObservationStatus.UNKNOWN))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_PENDING)
        self.assertTrue(session.is_open)
        self.assertEqual(
            [e.event_type for e in self.engine.events],
            [LiveEventType.LIVE_STARTED],
        )

    def test_live_during_offline_pending_cancels_close(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        session = self.engine.open_session
        assert session is not None

        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.engine.process(obs(5, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_CONFIRMED)
        self.assertTrue(session.is_open)
        self.assertEqual(len(self.engine.sessions), 1)

    def test_repeated_offline_after_close_does_not_duplicate_end_event(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.engine.process(obs(5, ObservationStatus.OFFLINE))
        for index in range(6, 10):
            self.engine.process(obs(index, ObservationStatus.OFFLINE))

        self.assertEqual(len(self.engine.sessions), 1)
        self.assertEqual(
            [e.event_type for e in self.engine.events],
            [LiveEventType.LIVE_STARTED, LiveEventType.LIVE_ENDED],
        )

    def test_duplicate_observation_id_is_idempotent(self) -> None:
        self.bootstrap_offline()
        first = obs(2, ObservationStatus.LIVE, observation_id="same-id")
        duplicate = obs(3, ObservationStatus.LIVE, observation_id="same-id")

        self.engine.process(first)
        result = self.engine.process(duplicate)
        self.assertTrue(result.duplicate)
        self.assertFalse(result.accepted)
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.assertEqual(len(self.engine.sessions), 0)

        self.engine.process(obs(4, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(len(self.engine.sessions), 1)

    def test_two_complete_cycles_create_two_distinct_sessions_and_exact_events(self) -> None:
        statuses = [
            ObservationStatus.OFFLINE,
            ObservationStatus.LIVE,
            ObservationStatus.LIVE,
            ObservationStatus.OFFLINE,
            ObservationStatus.OFFLINE,
            ObservationStatus.LIVE,
            ObservationStatus.LIVE,
            ObservationStatus.OFFLINE,
            ObservationStatus.OFFLINE,
        ]
        for index, status in enumerate(statuses, start=1):
            self.engine.process(obs(index, status))

        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(len(self.engine.sessions), 2)
        self.assertEqual([s.session_id for s in self.engine.sessions], [1, 2])
        self.assertTrue(all(not session.is_open for session in self.engine.sessions))
        self.assertEqual(
            [e.event_type for e in self.engine.events],
            [
                LiveEventType.LIVE_STARTED,
                LiveEventType.LIVE_ENDED,
                LiveEventType.LIVE_STARTED,
                LiveEventType.LIVE_ENDED,
            ],
        )

    def test_config_rejects_zero_confirmation_threshold(self) -> None:
        with self.assertRaises(ValueError):
            EngineConfig(live_confirmations_required=0)
        with self.assertRaises(ValueError):
            EngineConfig(offline_confirmations_required=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
