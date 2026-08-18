#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform_health import CanonicalStatus, HealthState
from source_composition import (
    CompositionReason,
    SourceComposer,
    SourceCompositionPolicy,
    SourceObservation,
    SourceRole,
)

GATE0B_DIR = Path(__file__).resolve().parents[1] / "gate0b"
if str(GATE0B_DIR) not in sys.path:
    sys.path.insert(0, str(GATE0B_DIR))

from state_engine import (  # noqa: E402
    EngineConfig,
    EngineState,
    LiveObservation,
    ObservationStatus,
    StateEngine,
)


TZ = timezone(timedelta(hours=8))
BASE = datetime(2026, 8, 18, 9, 0, tzinfo=TZ)


def policy() -> SourceCompositionPolicy:
    return SourceCompositionPolicy(
        primary_source="streamget",
        roles={
            "streamget": SourceRole.PRIMARY_STATUS,
            "tikhub": SourceRole.POSITIVE_STATUS,
            "f2": SourceRole.POSITIVE_STATUS,
            "backup": SourceRole.FULL_STATUS,
            "meta": SourceRole.METADATA_ONLY,
        },
        metadata_priority=("streamget", "tikhub", "f2", "meta", "backup"),
        max_fallback_lag_seconds=120,
        conflict_window_seconds=120,
        max_metadata_lag_seconds=300,
    )


def obs(
    source: str,
    number: int,
    status: CanonicalStatus,
    *,
    at: datetime | None = None,
    observation_id: str | None = None,
    health: HealthState = HealthState.HEALTHY,
    room_id: str | None = None,
    title: str | None = None,
    live_url: str | None = None,
    source_started_at: datetime | None = None,
    account_id: str = "douyin:creator-1",
) -> SourceObservation:
    return SourceObservation(
        account_id=account_id,
        source_id=source,
        observation_id=observation_id or f"{source}-{number}",
        observed_at=at or BASE + timedelta(seconds=number),
        status=status,
        health=health,
        room_id=room_id,
        title=title,
        live_url=live_url,
        source_started_at=source_started_at,
    )


class SourceCompositionGate0C4Tests(unittest.TestCase):
    def test_01_primary_live_is_canonical(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(obs("streamget", 1, CanonicalStatus.LIVE))
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.LIVE)
        self.assertEqual(result.reason, CompositionReason.PRIMARY)

    def test_02_primary_offline_is_canonical(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(obs("streamget", 1, CanonicalStatus.OFFLINE))
        self.assertEqual(composer.compose().status, CanonicalStatus.OFFLINE)

    def test_03_primary_unknown_allows_positive_live_fallback(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.UNKNOWN),
            obs("tikhub", 1, CanonicalStatus.LIVE),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.LIVE)
        self.assertEqual(result.reason, CompositionReason.POSITIVE_FALLBACK)

    def test_04_positive_source_offline_can_never_create_offline(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.UNKNOWN),
            obs("tikhub", 1, CanonicalStatus.OFFLINE),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(result.reason, CompositionReason.NO_DECISIVE_STATUS)

    def test_05_primary_offline_and_recent_positive_live_conflict_to_unknown(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.OFFLINE),
            obs("tikhub", 1, CanonicalStatus.LIVE),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(result.reason, CompositionReason.CONFLICT)
        self.assertEqual(set(result.conflict_sources), {"streamget", "tikhub"})

    def test_06_primary_live_ignores_positive_source_offline_claim(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.LIVE),
            obs("tikhub", 1, CanonicalStatus.OFFLINE),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.LIVE)
        self.assertEqual(result.reason, CompositionReason.PRIMARY)

    def test_07_full_status_backup_can_conflict_with_primary(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.LIVE),
            obs("backup", 1, CanonicalStatus.OFFLINE),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(result.reason, CompositionReason.CONFLICT)

    def test_08_old_conflicting_fallback_outside_window_does_not_override_primary(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("tikhub", 1, CanonicalStatus.LIVE, at=BASE),
            obs("streamget", 2, CanonicalStatus.OFFLINE, at=BASE + timedelta(minutes=3)),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.OFFLINE)
        self.assertEqual(result.reason, CompositionReason.PRIMARY)

    def test_09_missing_metadata_never_changes_primary_status(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(obs("streamget", 1, CanonicalStatus.LIVE))
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.LIVE)
        self.assertIsNone(result.room_id)
        self.assertIsNone(result.source_started_at)

    def test_10_auxiliary_room_id_enriches_primary_live_without_status_override(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.LIVE, title="primary title"),
            obs("tikhub", 1, CanonicalStatus.LIVE, room_id="room-123"),
        ])
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.LIVE)
        self.assertEqual(result.room_id, "room-123")
        self.assertEqual(result.metadata_provenance["room_id"].source_id, "tikhub")
        self.assertEqual(result.title, "primary title")

    def test_11_metadata_only_source_cannot_create_live_or_offline(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(obs("meta", 1, CanonicalStatus.LIVE, room_id="room-meta"))
        result = composer.compose()
        self.assertEqual(result.status, CanonicalStatus.UNKNOWN)
        self.assertEqual(result.room_id, "room-meta")

    def test_12_unhealthy_decisive_primary_fact_is_not_rewritten_by_health(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(
            obs(
                "streamget",
                1,
                CanonicalStatus.LIVE,
                health=HealthState.DEGRADED,
            )
        )
        self.assertEqual(composer.compose().status, CanonicalStatus.LIVE)

    def test_13_unavailable_unknown_primary_is_not_offline(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(
            obs(
                "streamget",
                1,
                CanonicalStatus.UNKNOWN,
                health=HealthState.UNAVAILABLE,
            )
        )
        self.assertEqual(composer.compose().status, CanonicalStatus.UNKNOWN)

    def test_14_duplicate_observation_id_is_idempotent(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        first = obs("streamget", 1, CanonicalStatus.LIVE)
        composer.ingest(first)
        duplicate = composer.ingest(first)
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.accepted)
        self.assertEqual(composer.compose().status, CanonicalStatus.LIVE)

    def test_15_older_same_source_result_is_stale_and_cannot_regress(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest(obs("streamget", 2, CanonicalStatus.LIVE, at=BASE + timedelta(seconds=20)))
        stale = composer.ingest(obs("streamget", 1, CanonicalStatus.OFFLINE, at=BASE + timedelta(seconds=10)))
        self.assertTrue(stale.stale)
        self.assertEqual(composer.compose().status, CanonicalStatus.LIVE)

    def test_16_snapshot_restore_preserves_latest_facts_and_idempotency(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        fact = obs("streamget", 1, CanonicalStatus.OFFLINE)
        composer.ingest(fact)
        restarted = SourceComposer.from_snapshot(composer.snapshot(), policy())
        self.assertEqual(restarted.compose().status, CanonicalStatus.OFFLINE)
        self.assertTrue(restarted.ingest(fact).duplicate)

    def test_17_source_started_at_is_explicit_metadata_with_provenance(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        started = BASE - timedelta(minutes=15)
        composer.ingest_many([
            obs("streamget", 2, CanonicalStatus.LIVE),
            obs("tikhub", 1, CanonicalStatus.LIVE, source_started_at=started),
        ])
        result = composer.compose()
        self.assertEqual(result.source_started_at, started)
        self.assertEqual(result.metadata_provenance["source_started_at"].source_id, "tikhub")

    def test_18_composition_conflict_unknown_cannot_close_gate0b_open_session(self) -> None:
        engine = StateEngine(EngineConfig(live_confirmations_required=1, offline_confirmations_required=1))
        engine.process(
            LiveObservation(
                observation_id="baseline-offline",
                status=ObservationStatus.OFFLINE,
                observed_at=BASE,
            )
        )
        engine.process(
            LiveObservation(
                observation_id="live",
                status=ObservationStatus.LIVE,
                observed_at=BASE + timedelta(seconds=1),
            )
        )
        self.assertEqual(engine.state, EngineState.LIVE_CONFIRMED)
        session_id = engine.open_session.session_id

        composer = SourceComposer("douyin:creator-1", policy())
        composer.ingest_many([
            obs("streamget", 3, CanonicalStatus.OFFLINE, at=BASE + timedelta(seconds=3)),
            obs("tikhub", 2, CanonicalStatus.LIVE, at=BASE + timedelta(seconds=2)),
        ])
        composed = composer.compose()
        self.assertEqual(composed.status, CanonicalStatus.UNKNOWN)

        engine.process(
            LiveObservation(
                observation_id="composed-conflict",
                status=ObservationStatus(composed.status.value),
                observed_at=composed.observed_at,
            )
        )
        self.assertEqual(engine.state, EngineState.LIVE_CONFIRMED)
        self.assertEqual(engine.open_session.session_id, session_id)

    def test_19_account_identity_mismatch_is_rejected(self) -> None:
        composer = SourceComposer("douyin:creator-1", policy())
        with self.assertRaises(ValueError):
            composer.ingest(obs("streamget", 1, CanonicalStatus.LIVE, account_id="douyin:other"))

    def test_20_invalid_policy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SourceCompositionPolicy(
                primary_source="streamget",
                roles={"streamget": SourceRole.POSITIVE_STATUS},
                metadata_priority=("streamget",),
            )


if __name__ == "__main__":
    unittest.main()
