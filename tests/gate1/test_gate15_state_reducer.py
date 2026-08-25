from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stage_letter.domain.live import LiveEventCause, LiveObservation, LiveStatus, SessionOrigin
from stage_letter.domain.state_engine import (
    EngineConfig,
    EngineSnapshot,
    EngineState,
    LiveStateReducer,
    TransitionIntentType,
)


ROOT = Path(__file__).resolve().parents[2]
STATE_ENGINE_PATH = ROOT / "stage_letter" / "domain" / "state_engine.py"


def _obs(
    oid: str,
    status: LiveStatus,
    minute: int,
    *,
    source_started_at: datetime | None = None,
    room_id: str | None = None,
) -> LiveObservation:
    return LiveObservation(
        observation_id=oid,
        account_id="101",
        status=status,
        observed_at=datetime(2026, 8, 19, 8, minute, tzinfo=timezone.utc),
        source="gate15.contract",
        source_started_at=source_started_at,
        room_id=room_id,
    )


class Gate15StateReducerContractTests(unittest.TestCase):
    def test_confirmation_thresholds_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            EngineConfig(live_confirmations_required=0)
        with self.assertRaises(ValueError):
            EngineConfig(offline_confirmations_required=0)

    def test_unknown_advances_watermark_without_decisive_state_change(self) -> None:
        reducer = LiveStateReducer()
        result = reducer.process(_obs("monitor:u1", LiveStatus.UNKNOWN, 1))
        self.assertTrue(result.accepted)
        self.assertEqual(EngineState.UNKNOWN, reducer.state)
        self.assertEqual(0, reducer.live_streak)
        self.assertEqual(0, reducer.offline_streak)
        self.assertEqual((), result.emitted_intents)
        self.assertEqual(datetime(2026, 8, 19, 8, 1, tzinfo=timezone.utc), reducer.observation_watermark)

    def test_first_offline_confirms_offline_without_session_or_event_intent(self) -> None:
        reducer = LiveStateReducer()
        result = reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, reducer.state)
        self.assertFalse(reducer.session_open)
        self.assertEqual((), result.emitted_intents)

    def test_two_initial_live_observations_open_bootstrap_session(self) -> None:
        reducer = LiveStateReducer()
        started = datetime(2026, 8, 19, 7, 55, tzinfo=timezone.utc)
        first = reducer.process(_obs("monitor:b1", LiveStatus.LIVE, 1, source_started_at=started))
        second = reducer.process(_obs("monitor:b2", LiveStatus.LIVE, 2, source_started_at=started))

        self.assertEqual(EngineState.BOOTSTRAP_LIVE_PENDING, first.current_state)
        self.assertEqual(1, len(second.emitted_intents))
        intent = second.emitted_intents[0]
        self.assertIs(TransitionIntentType.OPEN_SESSION, intent.intent_type)
        self.assertIs(SessionOrigin.BOOTSTRAP_LIVE, intent.origin)
        self.assertIs(LiveEventCause.BOOTSTRAP_LIVE, intent.cause)
        self.assertEqual(started, intent.source_started_at)
        self.assertTrue(reducer.session_open)

    def test_bootstrap_live_pending_cancelled_by_explicit_offline(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:b1", LiveStatus.LIVE, 1))
        result = reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 2))
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, reducer.state)
        self.assertEqual((), result.emitted_intents)
        self.assertFalse(reducer.session_open)

    def test_confirmed_offline_then_two_live_opens_transition_session(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        first_live = reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2))
        second_live = reducer.process(_obs("monitor:l2", LiveStatus.LIVE, 3))

        self.assertEqual(EngineState.LIVE_PENDING, first_live.current_state)
        intent = second_live.emitted_intents[0]
        self.assertIs(TransitionIntentType.OPEN_SESSION, intent.intent_type)
        self.assertIs(SessionOrigin.TRANSITION, intent.origin)
        self.assertIs(LiveEventCause.TRANSITION, intent.cause)
        self.assertTrue(reducer.session_open)

    def test_two_offline_observations_close_confirmed_live_session(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2))
        reducer.process(_obs("monitor:l2", LiveStatus.LIVE, 3))
        first_offline = reducer.process(_obs("monitor:o2", LiveStatus.OFFLINE, 4))
        second_offline = reducer.process(_obs("monitor:o3", LiveStatus.OFFLINE, 5))

        self.assertEqual(EngineState.OFFLINE_PENDING, first_offline.current_state)
        intent = second_offline.emitted_intents[0]
        self.assertIs(TransitionIntentType.CLOSE_SESSION, intent.intent_type)
        self.assertIsNone(intent.origin)
        self.assertIs(LiveEventCause.TRANSITION, intent.cause)
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, reducer.state)
        self.assertFalse(reducer.session_open)

    def test_unknown_does_not_cancel_pending_decisive_streak(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2))
        result = reducer.process(_obs("monitor:u1", LiveStatus.UNKNOWN, 3))
        self.assertEqual(EngineState.LIVE_PENDING, reducer.state)
        self.assertEqual(1, reducer.live_streak)
        self.assertEqual((), result.emitted_intents)

    def test_live_cancels_pending_close_and_keeps_session_open(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2))
        reducer.process(_obs("monitor:l2", LiveStatus.LIVE, 3))
        reducer.process(_obs("monitor:o2", LiveStatus.OFFLINE, 4))
        result = reducer.process(_obs("monitor:l3", LiveStatus.LIVE, 5))
        self.assertEqual(EngineState.LIVE_CONFIRMED, reducer.state)
        self.assertTrue(reducer.session_open)
        self.assertEqual(0, reducer.offline_streak)
        self.assertEqual((), result.emitted_intents)

    def test_confirmed_live_room_change_rolls_session_without_deciding_live_state(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2, room_id="room-1"))
        reducer.process(_obs("monitor:l2", LiveStatus.LIVE, 3, room_id="room-1"))

        unchanged = reducer.process(
            _obs("monitor:l3", LiveStatus.LIVE, 4, room_id="room-1")
        )
        changed = reducer.process(
            _obs("monitor:l4", LiveStatus.LIVE, 5, room_id="room-2")
        )

        self.assertEqual((), unchanged.emitted_intents)
        self.assertEqual(1, len(changed.emitted_intents))
        self.assertIs(
            TransitionIntentType.ROLLOVER_SESSION,
            changed.emitted_intents[0].intent_type,
        )
        self.assertTrue(reducer.session_open)
        self.assertEqual("room-2", reducer.open_room_id)

    def test_duplicate_id_is_idempotent_and_wins_over_stale_classification(self) -> None:
        reducer = LiveStateReducer()
        original = _obs("monitor:x", LiveStatus.OFFLINE, 5)
        reducer.process(original)
        older_same_id = LiveObservation(
            observation_id="monitor:x",
            account_id="101",
            status=LiveStatus.LIVE,
            observed_at=original.observed_at - timedelta(minutes=2),
            source="gate15.contract",
        )
        result = reducer.process(older_same_id)
        self.assertFalse(result.accepted)
        self.assertTrue(result.duplicate)
        self.assertFalse(result.stale)
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, reducer.state)

    def test_new_stale_observation_is_seen_but_cannot_rewrite_state_or_watermark(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:new", LiveStatus.OFFLINE, 5))
        watermark = reducer.observation_watermark
        stale = _obs("monitor:stale", LiveStatus.LIVE, 2)
        result = reducer.process(stale)
        self.assertFalse(result.accepted)
        self.assertFalse(result.duplicate)
        self.assertTrue(result.stale)
        self.assertIn("monitor:stale", reducer.seen_observation_ids)
        self.assertEqual(watermark, reducer.observation_watermark)
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, reducer.state)

    def test_snapshot_round_trip_preserves_state_and_domain_layer_has_no_outer_imports(self) -> None:
        reducer = LiveStateReducer()
        reducer.process(_obs("monitor:o1", LiveStatus.OFFLINE, 1))
        reducer.process(_obs("monitor:l1", LiveStatus.LIVE, 2))
        snapshot = reducer.snapshot()
        restored = LiveStateReducer.from_snapshot(snapshot)
        self.assertEqual(snapshot, restored.snapshot())

        with self.assertRaises(AssertionError):
            LiveStateReducer.from_snapshot(
                EngineSnapshot(
                    state=EngineState.LIVE_CONFIRMED,
                    live_streak=0,
                    offline_streak=0,
                    seen_observation_ids=frozenset(),
                    observation_watermark=None,
                    session_open=False,
                )
            )

        source = STATE_ENGINE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(STATE_ENGINE_PATH))
        forbidden = (
            "stage_letter.application",
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "httpx",
            "streamget",
        )
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == p or module.startswith(p + ".") for p in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
