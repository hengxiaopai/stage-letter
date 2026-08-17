#!/usr/bin/env python3
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from state_engine import (
    EngineConfig,
    EngineState,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    ObservationStatus,
    SessionOrigin,
    StateEngine,
)

UTC = timezone.utc
BASE = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)


def obs(
    index: int,
    status: ObservationStatus,
    observation_id: str | None = None,
    *,
    observed_at: datetime | None = None,
    source_started_at: datetime | None = None,
) -> LiveObservation:
    return LiveObservation(
        observation_id=observation_id or f"obs-{index}",
        status=status,
        observed_at=observed_at or (BASE + timedelta(seconds=index)),
        source="gate0b-test",
        source_started_at=source_started_at,
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
        self.assertFalse(result.stale)
        self.assertEqual(self.engine.sessions, [])
        self.assertEqual(self.engine.events, [])

    def test_initial_live_enters_bootstrap_pending_then_adopts_live(self) -> None:
        first = self.engine.process(obs(1, ObservationStatus.LIVE))
        self.assertEqual(first.current_state, EngineState.BOOTSTRAP_LIVE_PENDING)
        self.assertEqual(self.engine.live_streak, 1)
        self.assertIsNone(self.engine.open_session)

        second = self.engine.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(second.current_state, EngineState.LIVE_CONFIRMED)
        session = self.engine.open_session
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.origin, SessionOrigin.BOOTSTRAP_LIVE)
        self.assertEqual(len(second.emitted_events), 1)
        self.assertEqual(second.emitted_events[0].event_type, LiveEventType.LIVE_STARTED)
        self.assertEqual(second.emitted_events[0].cause, LiveEventCause.BOOTSTRAP_LIVE)

    def test_bootstrap_unknown_pauses_and_offline_cancels(self) -> None:
        self.engine.process(obs(1, ObservationStatus.LIVE))
        self.engine.process(obs(2, ObservationStatus.UNKNOWN))
        self.assertEqual(self.engine.state, EngineState.BOOTSTRAP_LIVE_PENDING)
        self.assertEqual(self.engine.live_streak, 1)
        self.engine.process(obs(3, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(self.engine.sessions, [])
        self.assertEqual(self.engine.events, [])

    def test_bootstrap_source_started_at_is_provenance_not_opened_at(self) -> None:
        source_started = BASE - timedelta(minutes=20)
        self.engine.process(obs(1, ObservationStatus.LIVE, source_started_at=source_started))
        confirmation = obs(2, ObservationStatus.LIVE, source_started_at=source_started)
        self.engine.process(confirmation)
        session = self.engine.open_session
        assert session is not None
        self.assertEqual(session.opened_at, confirmation.observed_at)
        self.assertEqual(session.source_started_at, source_started)
        self.assertEqual(session.origin, SessionOrigin.BOOTSTRAP_LIVE)

    def test_explicit_offline_bootstraps_offline_confirmed(self) -> None:
        self.bootstrap_offline()
        self.assertIsNone(self.engine.open_session)

    def test_live_requires_two_confirmations_before_transition_session_open(self) -> None:
        self.bootstrap_offline()
        self.engine.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.assertIsNone(self.engine.open_session)

        result = self.engine.process(obs(3, ObservationStatus.LIVE))
        self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)
        session = self.engine.open_session
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.origin, SessionOrigin.TRANSITION)
        self.assertEqual(len(self.engine.sessions), 1)
        self.assertEqual(result.emitted_events[0].cause, LiveEventCause.TRANSITION)

    def test_pending_live_is_cancelled_by_explicit_offline(self) -> None:
        self.bootstrap_offline()
        self.engine.process(obs(2, ObservationStatus.LIVE))
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
        self.assertEqual([e.event_type for e in self.engine.events], [LiveEventType.LIVE_STARTED])

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
        self.assertEqual(result.emitted_events[0].event_type, LiveEventType.LIVE_ENDED)
        self.assertEqual(result.emitted_events[0].cause, LiveEventCause.TRANSITION)
        self.assertEqual(result.emitted_events[0].session_id, session.session_id)

    def test_bootstrap_session_can_close_without_fake_transition_start(self) -> None:
        self.engine.process(obs(1, ObservationStatus.LIVE))
        self.engine.process(obs(2, ObservationStatus.LIVE))
        session = self.engine.open_session
        assert session is not None
        self.engine.process(obs(3, ObservationStatus.OFFLINE))
        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.assertFalse(session.is_open)
        self.assertEqual(
            [(event.event_type, event.cause) for event in self.engine.events],
            [
                (LiveEventType.LIVE_STARTED, LiveEventCause.BOOTSTRAP_LIVE),
                (LiveEventType.LIVE_ENDED, LiveEventCause.TRANSITION),
            ],
        )

    def test_unknown_during_offline_pending_never_closes_session(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        session = self.engine.open_session
        assert session is not None

        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.engine.process(obs(5, ObservationStatus.UNKNOWN))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_PENDING)
        self.assertTrue(session.is_open)
        self.assertEqual([e.event_type for e in self.engine.events], [LiveEventType.LIVE_STARTED])

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

    def test_duplicate_observation_id_is_idempotent_before_stale_classification(self) -> None:
        self.bootstrap_offline()
        first = obs(2, ObservationStatus.LIVE, observation_id="same-id")
        duplicate = obs(
            3,
            ObservationStatus.LIVE,
            observation_id="same-id",
            observed_at=BASE - timedelta(seconds=10),
        )

        self.engine.process(first)
        result = self.engine.process(duplicate)
        self.assertTrue(result.duplicate)
        self.assertFalse(result.stale)
        self.assertFalse(result.accepted)
        self.assertEqual(self.engine.state, EngineState.LIVE_PENDING)
        self.assertEqual(len(self.engine.sessions), 0)

    def test_stale_new_observation_never_changes_state_streak_or_event(self) -> None:
        baseline = obs(10, ObservationStatus.OFFLINE)
        self.engine.process(baseline)
        watermark = self.engine.observation_watermark
        result = self.engine.process(
            obs(
                11,
                ObservationStatus.LIVE,
                observation_id="late-old-live",
                observed_at=baseline.observed_at - timedelta(seconds=5),
            )
        )
        self.assertTrue(result.stale)
        self.assertFalse(result.accepted)
        self.assertFalse(result.duplicate)
        self.assertEqual(self.engine.state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(self.engine.live_streak, 0)
        self.assertEqual(self.engine.events, [])
        self.assertEqual(self.engine.observation_watermark, watermark)
        self.assertIn("late-old-live", self.engine.snapshot().seen_observation_ids)

    def test_newer_unknown_advances_watermark_and_blocks_older_offline_close(self) -> None:
        self.bootstrap_offline()
        self.confirm_live(2)
        session = self.engine.open_session
        assert session is not None
        self.engine.process(obs(4, ObservationStatus.OFFLINE))
        self.assertEqual(self.engine.state, EngineState.OFFLINE_PENDING)
        self.assertEqual(self.engine.offline_streak, 1)

        newer_unknown = obs(10, ObservationStatus.UNKNOWN)
        self.engine.process(newer_unknown)
        stale = self.engine.process(
            obs(
                11,
                ObservationStatus.OFFLINE,
                observation_id="older-offline",
                observed_at=newer_unknown.observed_at - timedelta(seconds=1),
            )
        )
        self.assertTrue(stale.stale)
        self.assertEqual(self.engine.state, EngineState.OFFLINE_PENDING)
        self.assertEqual(self.engine.offline_streak, 1)
        self.assertTrue(session.is_open)
        self.assertEqual(len(self.engine.events), 1)

    def test_equal_timestamp_is_not_classified_stale(self) -> None:
        when = BASE + timedelta(seconds=20)
        self.engine.process(obs(20, ObservationStatus.OFFLINE, observed_at=when))
        result = self.engine.process(
            obs(21, ObservationStatus.OFFLINE, observed_at=when)
        )
        self.assertFalse(result.stale)
        self.assertTrue(result.accepted)
        self.assertEqual(self.engine.observation_watermark, when)

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
        self.assertTrue(all(session.origin is SessionOrigin.TRANSITION for session in self.engine.sessions))
        self.assertEqual(
            [e.event_type for e in self.engine.events],
            [
                LiveEventType.LIVE_STARTED,
                LiveEventType.LIVE_ENDED,
                LiveEventType.LIVE_STARTED,
                LiveEventType.LIVE_ENDED,
            ],
        )

    def test_threshold_one_confirms_immediately_for_bootstrap_and_close(self) -> None:
        engine = StateEngine(
            EngineConfig(live_confirmations_required=1, offline_confirmations_required=1)
        )
        live = engine.process(obs(1, ObservationStatus.LIVE))
        self.assertEqual(live.current_state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(engine.open_session.origin, SessionOrigin.BOOTSTRAP_LIVE)
        ended = engine.process(obs(2, ObservationStatus.OFFLINE))
        self.assertEqual(ended.current_state, EngineState.OFFLINE_CONFIRMED)
        self.assertIsNone(engine.open_session)

    def test_config_rejects_zero_confirmation_threshold(self) -> None:
        with self.assertRaises(ValueError):
            EngineConfig(live_confirmations_required=0)
        with self.assertRaises(ValueError):
            EngineConfig(offline_confirmations_required=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
