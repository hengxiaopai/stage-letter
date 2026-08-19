from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.platforms import CreatorProfileSnapshot, LiveSnapshot, ResolvedCreator
from stage_letter.application.ports import LiveRepository
from stage_letter.application.services.monitoring_probe import (
    MonitoringProbeApplicationService,
    MonitoringProbeRequest,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveObservation, LiveStatus
from stage_letter.infrastructure.db.models import LiveObservationModel
from stage_letter.infrastructure.db.repositories.live import SQLAlchemyLiveRepository
from workers.monitoring.scheduler import make_probe_id


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "d14e7c9a5b30_gate14_monitor_probe_identity.py"
REPOSITORY = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories" / "live.py"
PROBE_SERVICE = ROOT / "stage_letter" / "application" / "services" / "monitoring_probe.py"
DURABILITY_PROBE = ROOT / "scripts" / "gate14_observation_durability_probe.py"


def _account() -> PlatformAccount:
    return PlatformAccount(
        account_id="101",
        creator_id="201",
        platform="douyin",
        platform_user_id="sec-101",
        enabled=True,
    )


def _observation(source: str = "winner.source") -> LiveObservation:
    return LiveObservation(
        observation_id="monitor:race-contract",
        account_id="101",
        status=LiveStatus.LIVE,
        observed_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
        source=source,
    )


class _Creators:
    async def get_account(self, account_id: str):
        return _account() if account_id == "101" else None


class _RaceLive:
    def __init__(self, *, expose_winner: bool) -> None:
        self.expose_winner = expose_winner
        self.winner: LiveObservation | None = None
        self.get_calls = 0
        self.append_calls = 0

    async def get_observation(self, account_id: str, observation_id: str):
        self.get_calls += 1
        return self.winner

    async def append_observation(self, observation: LiveObservation) -> bool:
        self.append_calls += 1
        if self.expose_winner:
            self.winner = _observation("other.process")
        return False


class _Uow:
    def __init__(self, live: _RaceLive) -> None:
        self.creators = _Creators()
        self.live = live
        self.commit_count = 0
        self.active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.active = False
        return False

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        return None


class _Adapter:
    platform = "douyin"

    def __init__(self, uow: _Uow) -> None:
        self.uow = uow

    async def resolve_creator(self, input: str) -> ResolvedCreator:
        return ResolvedCreator(platform="douyin", platform_user_id=input)

    async def get_creator_profile(self, account: PlatformAccount) -> CreatorProfileSnapshot:
        return CreatorProfileSnapshot(
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            observed_at=datetime.now(timezone.utc),
        )

    async def get_live_snapshot(self, account: PlatformAccount) -> LiveSnapshot:
        if self.uow.active:
            raise AssertionError("provider I/O must stay outside UnitOfWork")
        return LiveSnapshot(
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            status=LiveStatus.LIVE,
            observed_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
            source="this.process",
        )


class Gate14DurabilityContractTests(unittest.IsolatedAsyncioTestCase):
    def test_migration_extends_current_head_with_partial_monitor_unique_index(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "d14e7c9a5b30"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "c91e8d2f4a10"', source)
        self.assertIn('INDEX_NAME = "uq_g14_monitor_probe_identity"', source)
        self.assertIn("observation_id LIKE 'monitor:%'", source)
        self.assertIn('["platform_account_id", "observation_id"]', source)
        self.assertIn("unique=True", source)

    def test_migration_refuses_preexisting_monitor_duplicates_without_rewriting_evidence(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("HAVING COUNT(*) > 1", source)
        self.assertIn("raise RuntimeError", source)
        self.assertNotIn("DELETE FROM live_observations", source)
        self.assertNotIn("UPDATE live_observations", source)

    def test_model_declares_same_partial_unique_identity(self) -> None:
        indexes = {index.name: index for index in LiveObservationModel.__table__.indexes}
        index = indexes["uq_g14_monitor_probe_identity"]
        self.assertTrue(index.unique)
        self.assertEqual(
            ["platform_account_id", "observation_id"],
            [column.name for column in index.columns],
        )
        predicate = str(index.dialect_options["postgresql"]["where"])
        self.assertIn("observation_id LIKE 'monitor:%'", predicate)

    def test_live_repository_insert_contract_reports_winner_or_loser(self) -> None:
        signature = inspect.signature(LiveRepository.append_observation)
        self.assertEqual("bool", signature.return_annotation)
        concrete = inspect.signature(SQLAlchemyLiveRepository.append_observation)
        self.assertEqual("bool", concrete.return_annotation)

    def test_repository_insert_handles_all_unique_conflicts_and_returns_inserted_row_signal(self) -> None:
        source = inspect.getsource(SQLAlchemyLiveRepository.append_observation)
        self.assertIn(".on_conflict_do_nothing()", source)
        self.assertNotIn("constraint=", source)
        self.assertIn(".returning(LiveObservationModel.id)", source)
        self.assertIn("scalar_one_or_none() is not None", source)

    def test_monitoring_probe_ids_are_namespaced_for_partial_db_identity(self) -> None:
        request = MonitoringProbeRequest("monitor:contract", "101")
        self.assertEqual("monitor:contract", request.probe_id)
        with self.assertRaises(ValueError):
            MonitoringProbeRequest("legacy-or-manual", "101")
        with self.assertRaises(ValueError):
            MonitoringProbeRequest("monitor:" + "x" * 248, "101")

    async def test_insert_race_loser_reuses_durable_winner_without_commit(self) -> None:
        live = _RaceLive(expose_winner=True)
        uow = _Uow(live)
        adapter = _Adapter(uow)
        service = MonitoringProbeApplicationService(lambda: uow, lambda platform: adapter)  # type: ignore[arg-type]

        result = await service.execute(MonitoringProbeRequest("monitor:race-contract", "101"))

        self.assertTrue(result.reused_existing)
        self.assertEqual("other.process", result.observation.source)
        self.assertEqual(1, live.append_calls)
        self.assertEqual(0, uow.commit_count)

    async def test_insert_race_without_readable_winner_is_explicit_invariant_failure(self) -> None:
        live = _RaceLive(expose_winner=False)
        uow = _Uow(live)
        adapter = _Adapter(uow)
        service = MonitoringProbeApplicationService(lambda: uow, lambda platform: adapter)  # type: ignore[arg-type]

        with self.assertRaises(ApplicationInvariantError):
            await service.execute(MonitoringProbeRequest("monitor:race-contract", "101"))
        self.assertEqual(1, live.append_calls)
        self.assertEqual(0, uow.commit_count)

    def test_scheduler_generated_probe_id_is_monitor_namespaced_and_bounded(self) -> None:
        probe_id = make_probe_id("cycle-durable", "101")
        self.assertTrue(probe_id.startswith("monitor:"))
        self.assertLessEqual(len(probe_id), 255)
        self.assertEqual(probe_id, make_probe_id("cycle-durable", "101"))

    def test_postgres_probe_requires_migration_race_restart_and_disclaims_provider_exactly_once(self) -> None:
        source = DURABILITY_PROBE.read_text(encoding="utf-8")
        self.assertIn('EXPECTED_HEAD = "d14e7c9a5b30"', source)
        self.assertIn("asyncio.gather", source)
        self.assertIn("await engine.dispose()", source)
        self.assertIn('"row_count_after_engine_restart"', source)
        self.assertIn('"provider_exactly_once_claimed": False', source)
        service_source = PROBE_SERVICE.read_text(encoding="utf-8")
        self.assertNotIn("LiveSession", service_source)
        self.assertNotIn("LiveEvent", service_source)
        self.assertNotIn("Notification", service_source)


if __name__ == "__main__":
    unittest.main()
