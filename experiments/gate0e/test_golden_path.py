#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from golden_path import (
    CanonicalStatus,
    DeliveryRetryMachine,
    ExecutionState,
    GoldenPathHarness,
    GoldenTarget,
    GrantState,
    HealthState,
    ProviderOutcome,
    SourceObservation,
)

from notification_truth import DeliveryLedger, EligibilityReason
from state_engine import EngineState, LiveEventCause, LiveEventType, SessionOrigin


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 18, 16, 45, tzinfo=TZ)
ACCOUNT = "douyin:creator-golden"


def source(
    observation_id: str,
    at: datetime,
    status: CanonicalStatus,
    *,
    source_id: str = "streamget",
    title: str | None = None,
    live_url: str | None = None,
    source_started_at: datetime | None = None,
    health: HealthState = HealthState.HEALTHY,
) -> SourceObservation:
    return SourceObservation(
        account_id=ACCOUNT,
        source_id=source_id,
        observation_id=observation_id,
        observed_at=at,
        status=status,
        health=health,
        title=title,
        live_url=live_url,
        source_started_at=source_started_at,
    )


class GoldenPathGate0ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "gate0e.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def harness(self, *, target: GoldenTarget | None = None) -> GoldenPathHarness:
        return GoldenPathHarness(
            db_path=self.db,
            account_id=ACCOUNT,
            target=target or GoldenTarget(user_id="user-1"),
        )

    def drive_transition_live(self, h: GoldenPathHarness):
        h.process_source(source("off-1", BASE, CanonicalStatus.OFFLINE))
        first = h.process_source(source("live-1", BASE + timedelta(seconds=30), CanonicalStatus.LIVE))
        second = h.process_source(
            source(
                "live-2",
                BASE + timedelta(seconds=60),
                CanonicalStatus.LIVE,
                title="珩小派开播",
                live_url="https://live.douyin.com/golden",
                source_started_at=BASE + timedelta(seconds=20),
            )
        )
        return first, second

    def test_01_offline_live_live_emits_transition_live_started(self) -> None:
        h = self.harness()
        first, second = self.drive_transition_live(h)
        self.assertEqual(first.state_result.current_state, EngineState.LIVE_PENDING)
        self.assertEqual(second.state_result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(len(second.notification_events), 1)
        event = second.notification_events[0]
        self.assertEqual(event.event_type.value, LiveEventType.LIVE_STARTED.value)
        self.assertEqual(event.cause.value, LiveEventCause.TRANSITION.value)
        snapshot = h.live_snapshot
        self.assertEqual(snapshot.open_session.origin, SessionOrigin.TRANSITION)

    def test_02_transition_creates_exactly_one_eligible_delivery(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        self.assertEqual(len(second.eligibility), 1)
        self.assertTrue(second.eligibility[0].eligible)
        self.assertEqual(second.eligibility[0].reason, EligibilityReason.ELIGIBLE)
        self.assertEqual(len(second.deliveries), 1)
        self.assertTrue(second.deliveries[0].created)
        self.assertEqual(h.delivery_count, 1)

    def test_03_sent_completes_delivery_without_inferred_grant_exhaustion(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        delivery = second.deliveries[0].delivery
        self.assertIsNotNone(delivery)
        done = h.apply_provider_result(
            delivery.key,
            outcome=ProviderOutcome.SENT,
            started_at=BASE + timedelta(seconds=61),
            completed_at=BASE + timedelta(seconds=62),
            provider_code="0",
            provider_message="ok",
        )
        runtime = h.runtime_for(delivery)
        self.assertEqual(done.state, ExecutionState.SENT)
        self.assertEqual(runtime.grant_state, GrantState.GRANTED)
        self.assertTrue(runtime.is_terminal)

    def test_04_replaying_same_source_observation_creates_no_second_delivery(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        replay_source = source(
            "live-2",
            BASE + timedelta(seconds=60),
            CanonicalStatus.LIVE,
            title="珩小派开播",
            live_url="https://live.douyin.com/golden",
            source_started_at=BASE + timedelta(seconds=20),
        )
        replay = h.process_source(replay_source)
        self.assertTrue(replay.source_ingest.duplicate)
        self.assertIsNone(replay.state_result)
        self.assertEqual(h.delivery_count, 1)
        self.assertEqual(len(second.deliveries), 1)

    def test_05_bootstrap_live_opens_session_but_never_notifies(self) -> None:
        h = self.harness()
        h.process_source(source("boot-live-1", BASE, CanonicalStatus.LIVE))
        second = h.process_source(source("boot-live-2", BASE + timedelta(seconds=30), CanonicalStatus.LIVE))
        self.assertEqual(second.state_result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(len(second.notification_events), 1)
        self.assertFalse(second.eligibility[0].eligible)
        self.assertEqual(second.eligibility[0].reason, EligibilityReason.BOOTSTRAP_LIVE)
        self.assertEqual(h.delivery_count, 0)
        self.assertEqual(h.live_snapshot.open_session.origin, SessionOrigin.BOOTSTRAP_LIVE)

    def test_06_unknown_probe_failure_never_closes_live_session(self) -> None:
        h = self.harness()
        self.drive_transition_live(h)
        before = h.live_snapshot.open_session.session_id
        unknown = h.process_source(
            source(
                "unknown-1",
                BASE + timedelta(seconds=90),
                CanonicalStatus.UNKNOWN,
                health=HealthState.DEGRADED,
            )
        )
        self.assertEqual(unknown.composed.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(unknown.state_result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(h.live_snapshot.open_session.session_id, before)
        self.assertEqual(h.delivery_count, 1)

    def test_07_cross_source_conflict_becomes_unknown_and_keeps_session_open(self) -> None:
        h = self.harness()
        self.drive_transition_live(h)
        h.process_source(
            source(
                "tik-live",
                BASE + timedelta(seconds=90),
                CanonicalStatus.LIVE,
                source_id="tikhub",
            )
        )
        conflict = h.process_source(
            source("primary-off", BASE + timedelta(seconds=100), CanonicalStatus.OFFLINE)
        )
        self.assertEqual(conflict.composed.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(conflict.state_result.current_state, EngineState.LIVE_CONFIRMED)
        self.assertIsNotNone(h.live_snapshot.open_session)

    def test_08_two_explicit_offline_observations_close_session_without_new_delivery(self) -> None:
        h = self.harness()
        self.drive_transition_live(h)
        first = h.process_source(source("end-1", BASE + timedelta(seconds=150), CanonicalStatus.OFFLINE))
        second = h.process_source(source("end-2", BASE + timedelta(seconds=180), CanonicalStatus.OFFLINE))
        self.assertEqual(first.state_result.current_state, EngineState.OFFLINE_PENDING)
        self.assertEqual(second.state_result.current_state, EngineState.OFFLINE_CONFIRMED)
        self.assertEqual(len(second.notification_events), 1)
        self.assertEqual(second.notification_events[0].event_type.value, LiveEventType.LIVE_ENDED.value)
        self.assertFalse(second.eligibility[0].eligible)
        self.assertEqual(second.eligibility[0].reason, EligibilityReason.WRONG_EVENT_TYPE)
        self.assertEqual(h.delivery_count, 1)
        self.assertIsNone(h.live_snapshot.open_session)

    def test_09_persistent_state_survives_process_restart(self) -> None:
        h = self.harness()
        self.drive_transition_live(h)
        before = h.live_snapshot
        restarted = GoldenPathHarness(
            db_path=self.db,
            account_id=ACCOUNT,
            target=GoldenTarget(user_id="user-1"),
        )
        after = restarted.live_snapshot
        self.assertEqual(after.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(after.open_session.session_id, before.open_session.session_id)
        self.assertEqual(after.events, before.events)
        self.assertEqual(after.observation_count, before.observation_count)

    def test_10_delivery_ledger_snapshot_restart_preserves_logical_idempotency(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        delivery = second.deliveries[0].delivery
        restored = DeliveryLedger.from_snapshot(h.ledger.snapshot())
        self.assertEqual(restored.count, 1)
        self.assertEqual(restored.get(delivery.key), delivery)

    def test_11_crash_after_begin_before_response_restores_ambiguous(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        delivery = second.deliveries[0].delivery
        runtime = h.runtime_for(delivery)
        started = runtime.begin_attempt(
            attempt_id="crash-window-attempt",
            started_at=BASE + timedelta(seconds=61),
        )
        self.assertTrue(started.started)
        restarted = DeliveryRetryMachine.from_snapshot(runtime.snapshot())
        self.assertEqual(restarted.state, ExecutionState.AMBIGUOUS)
        self.assertTrue(restarted.is_terminal)
        self.assertFalse(
            restarted.begin_attempt(
                attempt_id="blind-retry",
                started_at=BASE + timedelta(minutes=10),
            ).started
        )

    def test_12_provider_network_failure_never_mutates_creator_live_truth(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        delivery = second.deliveries[0].delivery
        live_session_id = h.live_snapshot.open_session.session_id
        done = h.apply_provider_result(
            delivery.key,
            outcome=ProviderOutcome.NETWORK_ERROR,
            started_at=BASE + timedelta(seconds=61),
            completed_at=BASE + timedelta(seconds=62),
        )
        self.assertEqual(done.state, ExecutionState.WAITING_RETRY)
        self.assertEqual(h.live_snapshot.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(h.live_snapshot.open_session.session_id, live_session_id)

    def test_13_live_metadata_context_preserves_title_url_and_source_start(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        event = second.notification_events[0]
        context = h.context_for_event(event.event_id)
        self.assertIsNotNone(context)
        self.assertEqual(context.title, "珩小派开播")
        self.assertEqual(context.live_url, "https://live.douyin.com/golden")
        self.assertEqual(context.source_started_at, BASE + timedelta(seconds=20))

    def test_14_non_granted_target_never_enters_delivery_runtime(self) -> None:
        h = self.harness(
            target=GoldenTarget(
                user_id="user-1",
                grant_state=GrantState.EXHAUSTED,
            )
        )
        _, second = self.drive_transition_live(h)
        self.assertEqual(len(second.eligibility), 1)
        self.assertFalse(second.eligibility[0].eligible)
        self.assertEqual(second.eligibility[0].reason, EligibilityReason.GRANT_NOT_GRANTED)
        self.assertEqual(h.delivery_count, 0)
        self.assertEqual(h.runtimes, {})

    def test_15_happy_path_event_and_delivery_identity_are_deterministic(self) -> None:
        h = self.harness()
        _, second = self.drive_transition_live(h)
        event = second.notification_events[0]
        delivery = second.deliveries[0].delivery
        self.assertEqual(event.event_id, f"{ACCOUNT}:LIVE_STARTED:1")
        self.assertEqual(delivery.key.live_event_id, event.event_id)
        self.assertEqual(delivery.session_id, "1")
        self.assertEqual(delivery.account_id, ACCOUNT)


if __name__ == "__main__":
    unittest.main()
