from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import ObservationReplayRecord
from stage_letter.application.services.live_consumption import (
    LiveObservationConsumptionApplicationService,
)
from stage_letter.application.services.live_transition import TransitionPersistenceResult
from stage_letter.application.services.state_replay import (
    StateReconstructionApplicationService,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import (
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveStatus,
    SessionOrigin,
)
from stage_letter.domain.state_engine import EngineState, TransitionIntentType
from workers.composition import build_worker_services


ROOT = Path(__file__).resolve().parents[2]
CONSUMER_PATH = ROOT / "stage_letter" / "application" / "services" / "live_consumption.py"

T0 = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _obs(
    sequence: int,
    status: LiveStatus,
    *,
    observed_at: datetime | None = None,
) -> ObservationReplayRecord:
    observation = LiveObservation(
        observation_id=f"monitor:o{sequence}",
        account_id="101",
        status=status,
        observed_at=observed_at or (T0 + timedelta(minutes=sequence)),
        source="gate15.consumer",
        source_started_at=(T0 - timedelta(minutes=2)) if status is LiveStatus.LIVE else None,
    )
    return ObservationReplayRecord(sequence=sequence, observation=observation)


class _Creators:
    async def get_account(self, account_id: str):
        if account_id != "101":
            return None
        return PlatformAccount(
            account_id="101",
            creator_id="201",
            platform="douyin",
            platform_user_id="sec-101",
            enabled=True,
        )


class _ReplayLive:
    def __init__(self, records: list[ObservationReplayRecord]) -> None:
        self.records = tuple(records)

    async def list_monitor_observations(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ):
        return tuple(
            record
            for record in self.records
            if record.sequence > after_sequence
        )[:limit]


class _ReplayUow:
    def __init__(self, records: list[ObservationReplayRecord]) -> None:
        self.creators = _Creators()
        self.live = _ReplayLive(records)
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        return None


class _Transitions:
    def __init__(self) -> None:
        self.calls: list[tuple[LiveObservation, object]] = []

    async def apply(self, observation: LiveObservation, intent):
        self.calls.append((observation, intent))
        origin = intent.origin or SessionOrigin.TRANSITION
        session = LiveSession(
            session_id="7001",
            account_id=observation.account_id,
            opened_at=intent.occurred_at,
            origin=origin,
            closed_at=(intent.occurred_at if intent.intent_type is TransitionIntentType.CLOSE_SESSION else None),
            source_started_at=intent.source_started_at,
        )
        event_type = (
            LiveEventType.LIVE_STARTED
            if intent.intent_type is TransitionIntentType.OPEN_SESSION
            else LiveEventType.LIVE_ENDED
        )
        event = LiveEvent(
            event_id=f"live-event:test-{len(self.calls)}",
            account_id=observation.account_id,
            session_id=session.session_id,
            event_type=event_type,
            cause=intent.cause,
            occurred_at=intent.occurred_at,
        )
        return TransitionPersistenceResult(
            session=session,
            event=event,
            reused_existing=len(self.calls) > 1,
        )


def _services(records: list[ObservationReplayRecord]):
    uow = _ReplayUow(records)
    reconstruction = StateReconstructionApplicationService(lambda: uow, page_size=2)  # type: ignore[arg-type]
    transitions = _Transitions()
    consumer = LiveObservationConsumptionApplicationService(reconstruction, transitions)  # type: ignore[arg-type]
    return uow, reconstruction, transitions, consumer


class Gate15ObservationConsumptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconstruct_before_target_excludes_target_from_prior_state(self) -> None:
        _, reconstruction, _, _ = _services([
            _obs(1, LiveStatus.LIVE),
            _obs(2, LiveStatus.LIVE),
        ])
        point = await reconstruction.reconstruct_before_observation("101", "monitor:o2")
        self.assertEqual(1, point.prior.observations_replayed)
        self.assertEqual(1, point.prior.last_sequence)
        self.assertEqual(EngineState.BOOTSTRAP_LIVE_PENDING, point.prior.snapshot.state)
        self.assertEqual("monitor:o2", point.target.observation.observation_id)

    async def test_reconstruct_before_missing_target_is_explicit_not_found(self) -> None:
        _, reconstruction, _, _ = _services([_obs(1, LiveStatus.OFFLINE)])
        with self.assertRaises(ApplicationNotFoundError):
            await reconstruction.reconstruct_before_observation("101", "monitor:missing")

    async def test_reconstruct_before_rejects_non_monitor_target(self) -> None:
        _, reconstruction, _, _ = _services([])
        with self.assertRaises(ValueError):
            await reconstruction.reconstruct_before_observation("101", "manual:1")

    async def test_first_offline_is_read_only_and_confirms_offline(self) -> None:
        uow, _, transitions, consumer = _services([_obs(1, LiveStatus.OFFLINE)])
        result = await consumer.consume("101", "monitor:o1")
        self.assertFalse(result.emitted_transition)
        self.assertEqual(EngineState.OFFLINE_CONFIRMED, result.process_result.current_state)
        self.assertEqual([], transitions.calls)
        self.assertEqual(0, uow.commit_count)

    async def test_unknown_is_read_only_and_non_decisive(self) -> None:
        _, _, transitions, consumer = _services([_obs(1, LiveStatus.UNKNOWN)])
        result = await consumer.consume("101", "monitor:o1")
        self.assertFalse(result.emitted_transition)
        self.assertEqual(EngineState.UNKNOWN, result.process_result.current_state)
        self.assertEqual([], transitions.calls)

    async def test_second_live_bootstrap_emits_only_target_open_transition(self) -> None:
        _, _, transitions, consumer = _services([
            _obs(1, LiveStatus.LIVE),
            _obs(2, LiveStatus.LIVE),
        ])
        result = await consumer.consume("101", "monitor:o2")
        self.assertTrue(result.emitted_transition)
        self.assertEqual(1, len(transitions.calls))
        intent = transitions.calls[0][1]
        self.assertEqual(TransitionIntentType.OPEN_SESSION, intent.intent_type)
        self.assertEqual(SessionOrigin.BOOTSTRAP_LIVE, intent.origin)
        self.assertEqual(LiveEventCause.BOOTSTRAP_LIVE, intent.cause)

    async def test_offline_to_repeated_live_emits_transition_open(self) -> None:
        _, _, transitions, consumer = _services([
            _obs(1, LiveStatus.OFFLINE),
            _obs(2, LiveStatus.LIVE),
            _obs(3, LiveStatus.LIVE),
        ])
        await consumer.consume("101", "monitor:o3")
        intent = transitions.calls[0][1]
        self.assertEqual(SessionOrigin.TRANSITION, intent.origin)
        self.assertEqual(LiveEventCause.TRANSITION, intent.cause)

    async def test_late_stale_target_never_persists_transition(self) -> None:
        newer = _obs(1, LiveStatus.OFFLINE, observed_at=T0 + timedelta(hours=1))
        late = _obs(2, LiveStatus.LIVE, observed_at=T0)
        _, _, transitions, consumer = _services([newer, late])
        result = await consumer.consume("101", "monitor:o2")
        self.assertTrue(result.process_result.stale)
        self.assertFalse(result.emitted_transition)
        self.assertEqual([], transitions.calls)

    async def test_historical_replay_intents_are_never_forwarded_to_persistence(self) -> None:
        _, _, transitions, consumer = _services([
            _obs(1, LiveStatus.LIVE),
            _obs(2, LiveStatus.LIVE),
            _obs(3, LiveStatus.UNKNOWN),
        ])
        result = await consumer.consume("101", "monitor:o3")
        self.assertEqual(2, result.prior_observations_replayed)
        self.assertFalse(result.emitted_transition)
        self.assertEqual([], transitions.calls)

    async def test_retry_reconstructs_same_target_and_delegates_same_intent(self) -> None:
        _, _, transitions, consumer = _services([
            _obs(1, LiveStatus.LIVE),
            _obs(2, LiveStatus.LIVE),
        ])
        first = await consumer.consume("101", "monitor:o2")
        second = await consumer.consume("101", "monitor:o2")
        self.assertEqual(2, len(transitions.calls))
        self.assertEqual(transitions.calls[0][0], transitions.calls[1][0])
        self.assertEqual(transitions.calls[0][1], transitions.calls[1][1])
        self.assertFalse(first.transition.reused_existing)  # type: ignore[union-attr]
        self.assertTrue(second.transition.reused_existing)  # type: ignore[union-attr]

    def test_worker_bundle_wires_consumer_without_construction_io(self) -> None:
        calls = 0

        def session_factory():
            nonlocal calls
            calls += 1
            return object()

        bundle = build_worker_services(session_factory)  # type: ignore[arg-type]
        self.assertEqual(0, calls)
        self.assertIs(bundle.live_observation_consumer._reconstruction, bundle.state_reconstruction)
        self.assertIs(bundle.live_observation_consumer._transitions, bundle.live_transitions)
        self.assertIs(
            bundle.state_reconstruction._uow_factory,
            bundle.live_transitions._uow_factory,
        )

    def test_consumer_has_no_infrastructure_provider_or_notification_dependency(self) -> None:
        tree = ast.parse(CONSUMER_PATH.read_text(encoding="utf-8"), filename=str(CONSUMER_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "workers",
            "api",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
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
        source = CONSUMER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("NotificationDelivery", source)
        self.assertNotIn("AdapterRegistry", source)
        self.assertNotIn("get_live_snapshot", source)


if __name__ == "__main__":
    unittest.main()
