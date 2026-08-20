from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stage_letter.application.services.detection_due import DueMonitoringTargetApplicationService
from stage_letter.detection.contracts import PollingTier
from stage_letter.detection.due import DetectionCadencePolicy, due_at, is_due, normalize_polling_tier
from stage_letter.detection.ports import DetectionScheduleRow
from stage_letter.domain.creators import PlatformAccount

ROOT = Path(__file__).resolve().parents[2]
INFRA_PATH = ROOT / "stage_letter" / "infrastructure" / "detection" / "scheduling.py"
COMPOSITION_PATH = ROOT / "workers" / "detection_composition.py"

T0 = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)


def _account(account_id: str, *, enabled: bool = True, platform: str = "douyin") -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform=platform,
        platform_user_id=f"provider-{account_id}",
        enabled=enabled,
    )


def _row(
    account_id: str,
    *,
    tier: str | None = "warm",
    last_probe_at: datetime | None = None,
    enabled: bool = True,
) -> DetectionScheduleRow:
    return DetectionScheduleRow(
        account=_account(account_id, enabled=enabled),
        polling_tier_raw=tier,
        last_probe_at=last_probe_at,
    )


class _Repository:
    def __init__(self, rows: tuple[DetectionScheduleRow, ...]) -> None:
        self.rows = rows
        self.calls: list[tuple[str | None, int]] = []

    async def list_schedule_rows(self, *, after_account_id=None, limit=100):
        self.calls.append((after_account_id, limit))
        after = int(after_account_id) if after_account_id is not None else -1
        candidates = [row for row in self.rows if int(row.account.account_id) > after]
        return tuple(candidates[:limit])


class Gate21DueSelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_default_cadence_is_hot_30_warm_60_cold_300(self) -> None:
        policy = DetectionCadencePolicy()
        self.assertEqual(timedelta(seconds=30), policy.interval(PollingTier.HOT))
        self.assertEqual(timedelta(seconds=60), policy.interval(PollingTier.WARM))
        self.assertEqual(timedelta(seconds=300), policy.interval(PollingTier.COLD))
        with self.assertRaises(ValueError):
            DetectionCadencePolicy(hot_seconds=0)
        with self.assertRaises(ValueError):
            DetectionCadencePolicy(hot_seconds=60, warm_seconds=30, cold_seconds=300)

    def test_legacy_null_defaults_warm_and_corrupt_tier_falls_back_cold(self) -> None:
        self.assertIs(PollingTier.WARM, normalize_polling_tier(None))
        self.assertIs(PollingTier.WARM, normalize_polling_tier("  "))
        self.assertIs(PollingTier.HOT, normalize_polling_tier("HOT"))
        self.assertIs(PollingTier.COLD, normalize_polling_tier("unexpected"))

    def test_due_boundary_is_inclusive_and_never_probed_is_due(self) -> None:
        policy = DetectionCadencePolicy()
        self.assertIsNone(due_at(tier=PollingTier.HOT, last_probe_at=None, policy=policy))
        self.assertTrue(is_due(now=T0, tier=PollingTier.HOT, last_probe_at=None, policy=policy))
        last = T0 - timedelta(seconds=30)
        self.assertTrue(is_due(now=T0, tier=PollingTier.HOT, last_probe_at=last, policy=policy))
        self.assertFalse(
            is_due(
                now=T0 - timedelta(microseconds=1),
                tier=PollingTier.HOT,
                last_probe_at=last,
                policy=policy,
            )
        )
        with self.assertRaises(ValueError):
            is_due(now=T0.replace(tzinfo=None), tier=PollingTier.HOT, last_probe_at=last, policy=policy)

    async def test_service_selects_only_accounts_due_for_their_tier(self) -> None:
        repo = _Repository(
            (
                _row("1", tier="hot", last_probe_at=T0 - timedelta(seconds=30)),
                _row("2", tier="warm", last_probe_at=T0 - timedelta(seconds=59)),
                _row("3", tier="cold", last_probe_at=T0 - timedelta(seconds=300)),
                _row("4", tier="hot", last_probe_at=T0 - timedelta(seconds=29)),
            )
        )
        service = DueMonitoringTargetApplicationService(repo, clock=lambda: T0)
        selected = await service.list_targets(limit=100)
        self.assertEqual(("1", "3"), tuple(item.account_id for item in selected))

    async def test_never_probed_accounts_are_immediately_due(self) -> None:
        service = DueMonitoringTargetApplicationService(
            _Repository((_row("10", tier=None, last_probe_at=None),)),
            clock=lambda: T0,
        )
        selected = await service.list_targets()
        self.assertEqual(("10",), tuple(item.account_id for item in selected))

    async def test_service_scans_past_not_due_rows_to_fill_page(self) -> None:
        rows = tuple(
            _row(str(i), tier="cold", last_probe_at=T0)
            for i in range(1, 1001)
        ) + (_row("1001", tier="hot", last_probe_at=None),)
        repo = _Repository(rows)
        service = DueMonitoringTargetApplicationService(repo, clock=lambda: T0)
        selected = await service.list_targets(limit=1)
        self.assertEqual(("1001",), tuple(item.account_id for item in selected))
        self.assertEqual(2, len(repo.calls))

    async def test_disabled_account_is_defensively_excluded(self) -> None:
        service = DueMonitoringTargetApplicationService(
            _Repository((_row("20", last_probe_at=None, enabled=False),)),
            clock=lambda: T0,
        )
        self.assertEqual((), await service.list_targets())

    async def test_service_validates_limit_and_timezone_aware_clock(self) -> None:
        service = DueMonitoringTargetApplicationService(_Repository(()), clock=lambda: T0)
        with self.assertRaises(ValueError):
            await service.list_targets(limit=0)
        with self.assertRaises(ValueError):
            await service.list_targets(limit=1001)
        naive = DueMonitoringTargetApplicationService(
            _Repository(()), clock=lambda: T0.replace(tzinfo=None)
        )
        with self.assertRaises(ValueError):
            await naive.list_targets()

    def test_operational_repository_uses_separate_metadata_and_monitor_probe_history(self) -> None:
        source = INFRA_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("core.models", imports)
        self.assertNotIn("platform_adapters", imports)
        self.assertIn("MetaData()", source)
        self.assertIn('"polling_tier"', source)
        self.assertIn('observation_id.like("monitor:%")', source)
        self.assertIn("func.max(LiveObservationModel.created_at)", source)

    def test_gate2_composition_reuses_formal_scheduler_and_probe_ingress(self) -> None:
        source = COMPOSITION_PATH.read_text(encoding="utf-8")
        self.assertIn("MonitoringScheduler", source)
        self.assertIn("MonitoringProbeApplicationService", source)
        self.assertIn("DueMonitoringTargetApplicationService", source)
        self.assertNotIn("core.models", source)
        self.assertNotIn("workers.probe.worker", source)
        self.assertNotIn("send_wechat", source)


if __name__ == "__main__":
    unittest.main()
