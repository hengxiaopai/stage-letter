from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationInvariantError, ApplicationNotFoundError
from stage_letter.application.ports import LiveRepository
from stage_letter.application.services.live_transition import (
    LiveTransitionPersistenceApplicationService,
    make_live_event_id,
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
from stage_letter.domain.state_engine import TransitionIntent, TransitionIntentType
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "live_transition.py"

T0 = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
SOURCE_T0 = T0 - timedelta(minutes=3)


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="101",
        creator_id="201",
        platform="douyin",
        platform_user_id="sec-101",
        enabled=True,
    )


def _live_observation() -> LiveObservation:
    return LiveObservation(
        observation_id="monitor:open-101",
        account_id="101",
        status=LiveStatus.LIVE,
        observed_at=T0,
        source="provider.live",
        source_started_at=SOURCE_T0,
    )


def _offline_observation() -> LiveObservation:
    return LiveObservation(
        observation_id="monitor:close-101",
        account_id="101",
        status=LiveStatus.OFFLINE,
        observed_at=T0 + timedelta(hours=1),
        source="provider.offline",
    )


def _open_intent(*, bootstrap: bool = False) -> TransitionIntent:
    origin = SessionOrigin.BOOTSTRAP_LIVE if bootstrap else SessionOrigin.TRANSITION
    cause = LiveEventCause.BOOTSTRAP_LIVE if bootstrap else LiveEventCause.TRANSITION
    return TransitionIntent(
        intent_type=TransitionIntentType.OPEN_SESSION,
        occurred_at=T0,
        cause=cause,
        origin=origin,
        source_started_at=SOURCE_T0,
    )


def _close_intent() -> TransitionIntent:
    return TransitionIntent(
        intent_type=TransitionIntentType.CLOSE_SESSION,
        occurred_at=T0 + timedelta(hours=1),
        cause=LiveEventCause.TRANSITION,
    )


class _Creators:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    async def get_account(self, account_id: str):
        return _account() if self.exists and account_id == "101" else None


class _Live:
    def __init__(self, observation: LiveObservation | None) -> None:
        self.observation = observation
        self.open_session: LiveSession | None = None
        self.sessions: dict[str, LiveSession] = {}
        self.events: dict[str, LiveEvent] = {}
        self.created = 0
        self.saved = 0
        self.append_result = True
        self.lock_count = 0

    async def acquire_transition_lock(self, account_id: str) -> None:
        if account_id != "101":
            raise AssertionError("unexpected account lock")
        self.lock_count += 1

    async def get_observation(self, account_id: str, observation_id: str):
        if (
            self.observation is not None
            and self.observation.account_id == account_id
            and self.observation.observation_id == observation_id
        ):
            return self.observation
        return None

    async def get_event(self, event_id: str):
        return self.events.get(event_id)

    async def get_session(self, session_id: str):
        return self.sessions.get(session_id)

    async def get_open_session(self, account_id: str):
        if self.open_session is not None and self.open_session.account_id == account_id:
            return self.open_session
        return None

    async def create_session(
        self,
        account_id: str,
        *,
        opened_at: datetime,
        origin: SessionOrigin,
        source_started_at: datetime | None = None,
    ) -> LiveSession:
        self.created += 1
        session = LiveSession(
            session_id=str(9000 + self.created),
            account_id=account_id,
            opened_at=opened_at,
            origin=origin,
            source_started_at=source_started_at,
        )
        self.open_session = session
        self.sessions[session.session_id] = session
        return session

    async def save_session(self, session: LiveSession) -> None:
        self.saved += 1
        self.sessions[session.session_id] = session
        self.open_session = None if session.closed_at is not None else session

    async def append_event(self, event: LiveEvent) -> bool:
        if not self.append_result or event.event_id in self.events:
            return False
        self.events[event.event_id] = event
        return True


class _Uow:
    def __init__(self, live: _Live, *, account_exists: bool = True) -> None:
        self.creators = _Creators(account_exists)
        self.live = live
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback_count += 1
        return False

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


class Gate15TransitionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def test_event_id_is_stable_bounded_and_type_specific(self) -> None:
        start = make_live_event_id("101", "monitor:abc", LiveEventType.LIVE_STARTED)
        self.assertEqual(start, make_live_event_id("101", "monitor:abc", LiveEventType.LIVE_STARTED))
        end = make_live_event_id("101", "monitor:abc", LiveEventType.LIVE_ENDED)
        self.assertNotEqual(start, end)
        self.assertTrue(start.startswith("live-event:"))
        self.assertLessEqual(len(start), 255)

    def test_repository_port_allocates_session_and_reports_event_insert(self) -> None:
        self.assertIn("create_session", LiveRepository.__dict__)
        self.assertIn("acquire_transition_lock", LiveRepository.__dict__)
        self.assertEqual("LiveSession", inspect.signature(LiveRepository.create_session).return_annotation)
        self.assertEqual("bool", inspect.signature(LiveRepository.append_event).return_annotation)
        concrete = inspect.getsource(SQLAlchemyLiveRepository.create_session)
        self.assertIn(".returning(LiveSessionModel.id)", concrete)
        self.assertNotIn("session_id=", concrete)

    async def test_open_transition_allocates_session_and_event_in_one_commit(self) -> None:
        observation = _live_observation()
        live = _Live(observation)
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.apply(observation, _open_intent())

        self.assertFalse(result.reused_existing)
        self.assertEqual("9001", result.session.session_id)
        self.assertEqual(SessionOrigin.TRANSITION, result.session.origin)
        self.assertEqual(SOURCE_T0, result.session.source_started_at)
        self.assertEqual(LiveEventType.LIVE_STARTED, result.event.event_type)
        self.assertEqual(result.session.session_id, result.event.session_id)
        self.assertEqual(1, live.created)
        self.assertEqual(1, live.lock_count)
        self.assertEqual(1, uow.commit_count)

    async def test_bootstrap_open_preserves_origin_and_cause(self) -> None:
        observation = _live_observation()
        live = _Live(observation)
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.apply(observation, _open_intent(bootstrap=True))

        self.assertEqual(SessionOrigin.BOOTSTRAP_LIVE, result.session.origin)
        self.assertEqual(LiveEventCause.BOOTSTRAP_LIVE, result.event.cause)

    async def test_close_transition_closes_existing_session_and_emits_end(self) -> None:
        observation = _offline_observation()
        live = _Live(observation)
        session = LiveSession(
            session_id="7001",
            account_id="101",
            opened_at=T0,
            origin=SessionOrigin.TRANSITION,
            source_started_at=SOURCE_T0,
        )
        live.open_session = session
        live.sessions[session.session_id] = session
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.apply(observation, _close_intent())

        self.assertEqual("7001", result.session.session_id)
        self.assertEqual(observation.observed_at, result.session.closed_at)
        self.assertEqual(LiveEventType.LIVE_ENDED, result.event.event_type)
        self.assertEqual(1, live.saved)
        self.assertEqual(1, live.lock_count)
        self.assertEqual(1, uow.commit_count)

    async def test_existing_event_is_reused_without_second_commit(self) -> None:
        observation = _live_observation()
        intent = _open_intent()
        live = _Live(observation)
        event_id = make_live_event_id("101", observation.observation_id, LiveEventType.LIVE_STARTED)
        session = LiveSession(
            session_id="7002",
            account_id="101",
            opened_at=T0,
            origin=SessionOrigin.TRANSITION,
            source_started_at=SOURCE_T0,
        )
        event = LiveEvent(
            event_id=event_id,
            account_id="101",
            session_id="7002",
            event_type=LiveEventType.LIVE_STARTED,
            cause=LiveEventCause.TRANSITION,
            occurred_at=T0,
        )
        live.sessions[session.session_id] = session
        live.events[event.event_id] = event
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.apply(observation, intent)

        self.assertTrue(result.reused_existing)
        self.assertEqual(event, result.event)
        self.assertEqual(1, live.lock_count)
        self.assertEqual(0, live.created)
        self.assertEqual(0, uow.commit_count)

    async def test_missing_durable_observation_is_rejected(self) -> None:
        live = _Live(None)
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationNotFoundError):
            await service.apply(_live_observation(), _open_intent())
        self.assertEqual(1, live.lock_count)
        self.assertEqual(0, uow.commit_count)

    async def test_non_monitor_or_wrong_decisive_status_is_rejected(self) -> None:
        service = LiveTransitionPersistenceApplicationService(lambda: _Uow(_Live(None)))  # type: ignore[arg-type]
        non_monitor = LiveObservation(
            observation_id="manual:1",
            account_id="101",
            status=LiveStatus.LIVE,
            observed_at=T0,
            source="manual",
            source_started_at=SOURCE_T0,
        )
        with self.assertRaises(ApplicationInvariantError):
            await service.apply(non_monitor, _open_intent())

        wrong = LiveObservation(
            observation_id="monitor:wrong-status",
            account_id="101",
            status=LiveStatus.UNKNOWN,
            observed_at=T0,
            source="provider",
            source_started_at=SOURCE_T0,
        )
        with self.assertRaises(ApplicationInvariantError):
            await service.apply(wrong, _open_intent())

    async def test_durable_observation_mismatch_is_explicit_failure(self) -> None:
        requested = _live_observation()
        durable = LiveObservation(
            observation_id=requested.observation_id,
            account_id=requested.account_id,
            status=LiveStatus.OFFLINE,
            observed_at=requested.observed_at,
            source="other",
        )
        live = _Live(durable)
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.apply(requested, _open_intent())
        self.assertEqual(1, live.lock_count)
        self.assertEqual(0, uow.commit_count)

    async def test_close_without_open_session_is_explicit_failure(self) -> None:
        observation = _offline_observation()
        live = _Live(observation)
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.apply(observation, _close_intent())
        self.assertEqual(1, live.lock_count)
        self.assertEqual(0, uow.commit_count)

    async def test_event_insert_conflict_prevents_partial_commit(self) -> None:
        observation = _live_observation()
        live = _Live(observation)
        live.append_result = False
        uow = _Uow(live)
        service = LiveTransitionPersistenceApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.apply(observation, _open_intent())
        self.assertEqual(1, live.created)
        self.assertEqual(1, live.lock_count)
        self.assertEqual(0, uow.commit_count)
        self.assertEqual(1, uow.rollback_count)

    def test_application_service_has_no_infrastructure_provider_or_notification_dependency(self) -> None:
        tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"), filename=str(SERVICE_PATH))
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
        source = SERVICE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("NotificationDelivery", source)
        self.assertNotIn("AdapterRegistry", source)


if __name__ == "__main__":
    unittest.main()
