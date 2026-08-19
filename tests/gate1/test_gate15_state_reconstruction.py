from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import LiveRepository, ObservationReplayRecord
from stage_letter.application.services.state_replay import StateReconstructionApplicationService
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.domain.state_engine import EngineState
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "stage_letter" / "application" / "services" / "state_replay.py"
REPOSITORY = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories" / "live.py"
BASE = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)


def _account(account_id: str = "101") -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id="201",
        platform="douyin",
        platform_user_id="sec-101",
        enabled=True,
    )


def _obs(
    sequence: int,
    status: LiveStatus,
    *,
    offset: int,
    account_id: str = "101",
    observation_id: str | None = None,
) -> ObservationReplayRecord:
    return ObservationReplayRecord(
        sequence=sequence,
        observation=LiveObservation(
            observation_id=observation_id or f"monitor:replay-{sequence}",
            account_id=account_id,
            status=status,
            observed_at=BASE + timedelta(seconds=offset),
            source="gate15.replay",
        ),
    )


class _Creators:
    def __init__(self, account: PlatformAccount | None = None) -> None:
        self.account = _account() if account is None else account

    async def get_account(self, account_id: str):
        if self.account is None or self.account.account_id != account_id:
            return None
        return self.account


class _Live:
    def __init__(self, records: tuple[ObservationReplayRecord, ...]) -> None:
        self.records = records
        self.calls: list[tuple[str, int, int]] = []

    async def list_monitor_observations(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[ObservationReplayRecord, ...]:
        self.calls.append((account_id, after_sequence, limit))
        return tuple(
            record
            for record in self.records
            if record.sequence > after_sequence
        )[:limit]


class _Uow:
    def __init__(self, creators: _Creators, live: _Live) -> None:
        self.creators = creators
        self.live = live
        self.commit_count = 0
        self.enter_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        return None


class Gate15StateReconstructionTests(unittest.IsolatedAsyncioTestCase):
    def _service(
        self,
        records: tuple[ObservationReplayRecord, ...] = (),
        *,
        account: PlatformAccount | None = None,
        page_size: int = 500,
    ):
        creators = _Creators(account)
        live = _Live(records)
        uow = _Uow(creators, live)
        service = StateReconstructionApplicationService(
            lambda: uow,  # type: ignore[arg-type]
            page_size=page_size,
        )
        return service, uow, live

    def test_replay_record_requires_positive_sequence(self) -> None:
        with self.assertRaises(ValueError):
            ObservationReplayRecord(0, _obs(1, LiveStatus.OFFLINE, offset=0).observation)

    def test_live_repository_exposes_async_monitor_replay_port(self) -> None:
        self.assertTrue(inspect.iscoroutinefunction(LiveRepository.list_monitor_observations))
        self.assertTrue(
            inspect.iscoroutinefunction(SQLAlchemyLiveRepository.list_monitor_observations)
        )
        parameters = inspect.signature(LiveRepository.list_monitor_observations).parameters
        self.assertEqual(
            ("self", "account_id", "after_sequence", "limit"),
            tuple(parameters),
        )

    def test_sql_repository_filters_monitor_namespace_and_orders_by_durable_sequence(self) -> None:
        source = inspect.getsource(SQLAlchemyLiveRepository.list_monitor_observations)
        self.assertIn('.like("monitor:%")', source)
        self.assertIn("LiveObservationModel.id > after_sequence", source)
        self.assertIn(".order_by(LiveObservationModel.id.asc())", source)
        self.assertNotIn("LiveSessionModel", source)
        self.assertNotIn("LiveEventModel", source)

    async def test_empty_durable_history_reconstructs_unknown(self) -> None:
        service, uow, _ = self._service()
        result = await service.reconstruct("101")
        self.assertIs(EngineState.UNKNOWN, result.snapshot.state)
        self.assertFalse(result.snapshot.session_open)
        self.assertEqual(0, result.observations_replayed)
        self.assertEqual(0, result.last_sequence)
        self.assertEqual(0, uow.commit_count)

    async def test_explicit_offline_reconstructs_offline_confirmed(self) -> None:
        service, _, _ = self._service((_obs(1, LiveStatus.OFFLINE, offset=1),))
        result = await service.reconstruct("101")
        self.assertIs(EngineState.OFFLINE_CONFIRMED, result.snapshot.state)
        self.assertEqual(BASE + timedelta(seconds=1), result.snapshot.observation_watermark)
        self.assertFalse(result.snapshot.session_open)

    async def test_bootstrap_live_reconstructs_open_session_semantics(self) -> None:
        service, _, _ = self._service(
            (
                _obs(1, LiveStatus.LIVE, offset=1),
                _obs(2, LiveStatus.LIVE, offset=2),
            )
        )
        result = await service.reconstruct("101")
        self.assertIs(EngineState.LIVE_CONFIRMED, result.snapshot.state)
        self.assertTrue(result.snapshot.session_open)
        self.assertEqual(0, result.snapshot.live_streak)

    async def test_offline_to_live_transition_reconstructs_confirmed_live(self) -> None:
        service, _, _ = self._service(
            (
                _obs(1, LiveStatus.OFFLINE, offset=1),
                _obs(2, LiveStatus.LIVE, offset=2),
                _obs(3, LiveStatus.LIVE, offset=3),
            )
        )
        result = await service.reconstruct("101")
        self.assertIs(EngineState.LIVE_CONFIRMED, result.snapshot.state)
        self.assertTrue(result.snapshot.session_open)

    async def test_unknown_advances_watermark_without_rewriting_decisive_state(self) -> None:
        service, _, _ = self._service(
            (
                _obs(1, LiveStatus.OFFLINE, offset=1),
                _obs(2, LiveStatus.UNKNOWN, offset=5),
            )
        )
        result = await service.reconstruct("101")
        self.assertIs(EngineState.OFFLINE_CONFIRMED, result.snapshot.state)
        self.assertEqual(BASE + timedelta(seconds=5), result.snapshot.observation_watermark)

    async def test_persistence_order_preserves_late_observation_as_stale(self) -> None:
        service, _, _ = self._service(
            (
                _obs(1, LiveStatus.OFFLINE, offset=10),
                _obs(2, LiveStatus.LIVE, offset=5),
            )
        )
        result = await service.reconstruct("101")
        self.assertIs(EngineState.OFFLINE_CONFIRMED, result.snapshot.state)
        self.assertEqual(BASE + timedelta(seconds=10), result.snapshot.observation_watermark)
        self.assertEqual(
            {"monitor:replay-1", "monitor:replay-2"},
            set(result.snapshot.seen_observation_ids),
        )

    async def test_reconstruction_pages_by_opaque_sequence_without_commits(self) -> None:
        service, uow, live = self._service(
            tuple(_obs(index, LiveStatus.OFFLINE, offset=index) for index in range(1, 6)),
            page_size=2,
        )
        result = await service.reconstruct("101")
        self.assertEqual(5, result.observations_replayed)
        self.assertEqual(5, result.last_sequence)
        self.assertEqual(
            [("101", 0, 2), ("101", 2, 2), ("101", 4, 2)],
            live.calls,
        )
        self.assertEqual(0, uow.commit_count)

    async def test_replay_rejects_non_monitor_or_wrong_account_evidence(self) -> None:
        bad_namespace = _obs(
            1,
            LiveStatus.OFFLINE,
            offset=1,
            observation_id="legacy:1",
        )
        service, _, _ = self._service((bad_namespace,))
        with self.assertRaises(RuntimeError):
            await service.reconstruct("101")

        service, _, _ = self._service(
            (_obs(1, LiveStatus.OFFLINE, offset=1, account_id="999"),)
        )
        with self.assertRaises(RuntimeError):
            await service.reconstruct("101")

    async def test_missing_account_fails_before_replay(self) -> None:
        creators = _Creators()
        creators.account = None
        live = _Live((_obs(1, LiveStatus.OFFLINE, offset=1),))
        uow = _Uow(creators, live)
        service = StateReconstructionApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationNotFoundError):
            await service.reconstruct("101")
        self.assertEqual([], live.calls)

    def test_reconstruction_service_remains_infrastructure_free_and_read_only(self) -> None:
        source = SERVICE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SERVICE))
        forbidden = (
            "stage_letter.infrastructure",
            "workers",
            "api",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "httpx",
            "requests",
        )
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)
        self.assertNotIn("commit(", source)
        self.assertNotIn("save_session", source)
        self.assertNotIn("append_event", source)
        self.assertNotIn("Notification", source)


if __name__ == "__main__":
    unittest.main()
