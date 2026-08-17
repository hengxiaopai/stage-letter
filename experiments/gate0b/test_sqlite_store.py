#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlite_store import InjectedPersistenceFailure, PersistentStateEngine
from state_engine import (
    EngineConfig,
    EngineState,
    LiveEventType,
    LiveObservation,
    ObservationStatus,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 17, 15, 30, tzinfo=TZ)


def obs(number: int, status: ObservationStatus) -> LiveObservation:
    return LiveObservation(
        observation_id=f"obs-{number}",
        status=status,
        observed_at=BASE + timedelta(seconds=number),
        source="gate0b-test",
    )


class PersistentStateEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "gate0b.sqlite3"
        self.account_id = "douyin:sec_uid:test"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def store(self, config: EngineConfig | None = None) -> PersistentStateEngine:
        return PersistentStateEngine(self.db, self.account_id, config=config)

    def baseline(self, store: PersistentStateEngine) -> None:
        result = store.process(obs(1, ObservationStatus.OFFLINE))
        self.assertEqual(result.current_state, EngineState.OFFLINE_CONFIRMED)

    def open_live(self, store: PersistentStateEngine) -> None:
        self.baseline(store)
        store.process(obs(2, ObservationStatus.LIVE))
        result = store.process(obs(3, ObservationStatus.LIVE))
        self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)

    def test_01_offline_baseline_survives_restart(self) -> None:
        first = self.store()
        self.baseline(first)
        restarted = self.store()
        snapshot = restarted.snapshot()
        self.assertEqual(snapshot.state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(snapshot.observation_count, 1)

    def test_02_live_pending_survives_restart_and_confirms(self) -> None:
        first = self.store()
        self.baseline(first)
        first.process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(first.snapshot().state, EngineState.LIVE_PENDING)
        self.assertEqual(first.snapshot().live_streak, 1)

        restarted = self.store()
        result = restarted.process(obs(3, ObservationStatus.LIVE))
        snapshot = restarted.snapshot()
        self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertIsNotNone(snapshot.open_session)
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(snapshot.events[0].event_type, LiveEventType.LIVE_STARTED)

    def test_03_open_session_survives_restart(self) -> None:
        first = self.store()
        self.open_live(first)
        session_id = first.snapshot().open_session.session_id

        restarted = self.store()
        snapshot = restarted.snapshot()
        self.assertEqual(snapshot.state, EngineState.LIVE_CONFIRMED)
        self.assertIsNotNone(snapshot.open_session)
        self.assertEqual(snapshot.open_session.session_id, session_id)
        self.assertEqual(len(snapshot.events), 1)

    def test_04_offline_pending_survives_restart_and_closes_same_session(self) -> None:
        first = self.store()
        self.open_live(first)
        session_id = first.snapshot().open_session.session_id
        first.process(obs(4, ObservationStatus.OFFLINE))
        self.assertEqual(first.snapshot().state, EngineState.OFFLINE_PENDING)
        self.assertEqual(first.snapshot().offline_streak, 1)

        restarted = self.store()
        result = restarted.process(obs(5, ObservationStatus.OFFLINE))
        snapshot = restarted.snapshot()
        self.assertEqual(result.current_state, EngineState.OFFLINE_CONFIRMED)
        self.assertIsNone(snapshot.open_session)
        self.assertEqual(len(snapshot.sessions), 1)
        self.assertEqual(snapshot.sessions[0].session_id, session_id)
        self.assertIsNotNone(snapshot.sessions[0].closed_at)
        self.assertEqual(
            [event.event_type for event in snapshot.events],
            [LiveEventType.LIVE_STARTED, LiveEventType.LIVE_ENDED],
        )
        self.assertEqual(snapshot.events[1].session_id, session_id)

    def test_05_duplicate_observation_survives_restart_without_duplicate_event(self) -> None:
        first = self.store()
        self.open_live(first)
        before = first.snapshot()

        restarted = self.store()
        duplicate = restarted.process(obs(3, ObservationStatus.LIVE))
        after = restarted.snapshot()
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.accepted)
        self.assertEqual(after.observation_count, before.observation_count)
        self.assertEqual(len(after.sessions), 1)
        self.assertEqual(len(after.events), 1)

    def test_06_unknown_after_restart_never_closes_open_session(self) -> None:
        first = self.store()
        self.open_live(first)
        first.process(obs(4, ObservationStatus.OFFLINE))
        self.assertEqual(first.snapshot().state, EngineState.OFFLINE_PENDING)

        restarted = self.store()
        result = restarted.process(obs(5, ObservationStatus.UNKNOWN))
        snapshot = restarted.snapshot()
        self.assertEqual(result.current_state, EngineState.OFFLINE_PENDING)
        self.assertIsNotNone(snapshot.open_session)
        self.assertEqual(snapshot.offline_streak, 1)
        self.assertEqual(len(snapshot.events), 1)

    def test_07_session_sequence_continues_across_restart(self) -> None:
        first = self.store()
        self.open_live(first)
        first.process(obs(4, ObservationStatus.OFFLINE))
        first.process(obs(5, ObservationStatus.OFFLINE))

        restarted = self.store()
        restarted.process(obs(6, ObservationStatus.LIVE))
        restarted.process(obs(7, ObservationStatus.LIVE))
        snapshot = restarted.snapshot()
        self.assertEqual(snapshot.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual([session.session_id for session in snapshot.sessions], [1, 2])
        self.assertEqual(snapshot.open_session.session_id, 2)

    def test_08_transaction_rolls_back_after_observation_insert(self) -> None:
        store = self.store()
        self.baseline(store)
        before = store.snapshot()

        with self.assertRaises(InjectedPersistenceFailure):
            store.process(
                obs(2, ObservationStatus.LIVE),
                inject_failure_at="after_observation_insert",
            )

        after_failure = self.store().snapshot()
        self.assertEqual(after_failure.state, before.state)
        self.assertEqual(after_failure.observation_count, before.observation_count)
        self.assertEqual(after_failure.live_streak, 0)

        retry = self.store().process(obs(2, ObservationStatus.LIVE))
        self.assertEqual(retry.current_state, EngineState.LIVE_PENDING)

    def test_09_transaction_rolls_back_session_event_state_together(self) -> None:
        store = self.store()
        self.baseline(store)
        store.process(obs(2, ObservationStatus.LIVE))
        before = store.snapshot()

        with self.assertRaises(InjectedPersistenceFailure):
            store.process(
                obs(3, ObservationStatus.LIVE),
                inject_failure_at="after_state_write",
            )

        after_failure = self.store().snapshot()
        self.assertEqual(after_failure.state, EngineState.LIVE_PENDING)
        self.assertEqual(after_failure.live_streak, 1)
        self.assertEqual(after_failure.observation_count, before.observation_count)
        self.assertEqual(len(after_failure.sessions), 0)
        self.assertEqual(len(after_failure.events), 0)

        retry = self.store().process(obs(3, ObservationStatus.LIVE))
        snapshot = self.store().snapshot()
        self.assertEqual(retry.current_state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(len(snapshot.sessions), 1)
        self.assertEqual(len(snapshot.events), 1)

    def test_10_persisted_config_is_reused_and_mismatch_rejected(self) -> None:
        config = EngineConfig(live_confirmations_required=3, offline_confirmations_required=2)
        first = self.store(config)
        self.baseline(first)
        first.process(obs(2, ObservationStatus.LIVE))
        first.process(obs(3, ObservationStatus.LIVE))
        self.assertEqual(first.snapshot().state, EngineState.LIVE_PENDING)
        self.assertEqual(first.snapshot().live_streak, 2)

        restarted = self.store()
        result = restarted.process(obs(4, ObservationStatus.LIVE))
        self.assertEqual(result.current_state, EngineState.LIVE_CONFIRMED)

        with self.assertRaises(ValueError):
            self.store(EngineConfig(live_confirmations_required=2, offline_confirmations_required=2))


if __name__ == "__main__":
    unittest.main()
