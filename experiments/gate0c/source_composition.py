#!/usr/bin/env python3
"""Gate 0C-4 — deterministic multi-source composition policy.

This module separates status authority from metadata authority. It does not
open/close LiveSession objects and it never converts provider failure/absence
into creator OFFLINE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from platform_health import CanonicalStatus, HealthState


class SourceRole(str, Enum):
    PRIMARY_STATUS = "PRIMARY_STATUS"
    POSITIVE_STATUS = "POSITIVE_STATUS"
    FULL_STATUS = "FULL_STATUS"
    METADATA_ONLY = "METADATA_ONLY"


class CompositionReason(str, Enum):
    PRIMARY = "PRIMARY"
    POSITIVE_FALLBACK = "POSITIVE_FALLBACK"
    FULL_FALLBACK = "FULL_FALLBACK"
    CONFLICT = "CONFLICT"
    NO_DECISIVE_STATUS = "NO_DECISIVE_STATUS"


@dataclass(frozen=True)
class SourceObservation:
    account_id: str
    source_id: str
    observation_id: str
    observed_at: datetime
    status: CanonicalStatus
    health: HealthState = HealthState.STARTING
    room_id: str | None = None
    title: str | None = None
    live_url: str | None = None
    source_started_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.observation_id:
            raise ValueError("observation_id is required")


@dataclass(frozen=True)
class SourceCompositionPolicy:
    primary_source: str
    roles: Mapping[str, SourceRole]
    metadata_priority: tuple[str, ...]
    max_fallback_lag_seconds: int = 120
    conflict_window_seconds: int = 120
    max_metadata_lag_seconds: int = 300

    def __post_init__(self) -> None:
        if self.primary_source not in self.roles:
            raise ValueError("primary_source must exist in roles")
        if self.roles[self.primary_source] is not SourceRole.PRIMARY_STATUS:
            raise ValueError("primary_source must have PRIMARY_STATUS role")
        if self.max_fallback_lag_seconds < 0:
            raise ValueError("max_fallback_lag_seconds must be >= 0")
        if self.conflict_window_seconds < 0:
            raise ValueError("conflict_window_seconds must be >= 0")
        if self.max_metadata_lag_seconds < 0:
            raise ValueError("max_metadata_lag_seconds must be >= 0")
        if len(set(self.metadata_priority)) != len(self.metadata_priority):
            raise ValueError("metadata_priority must not contain duplicates")
        unknown = [source for source in self.metadata_priority if source not in self.roles]
        if unknown:
            raise ValueError(f"metadata_priority contains unknown sources: {unknown}")


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    duplicate: bool
    stale: bool
    source_id: str


@dataclass(frozen=True)
class FieldProvenance:
    source_id: str
    observation_id: str
    observed_at: datetime


@dataclass(frozen=True)
class ComposedObservation:
    account_id: str
    status: CanonicalStatus
    reason: CompositionReason
    observed_at: datetime | None
    status_sources: tuple[str, ...]
    conflict_sources: tuple[str, ...]
    room_id: str | None
    title: str | None
    live_url: str | None
    source_started_at: datetime | None
    metadata_provenance: Mapping[str, FieldProvenance]


@dataclass(frozen=True)
class ComposerSnapshot:
    account_id: str
    latest_by_source: tuple[SourceObservation, ...]
    seen_observation_ids: frozenset[str]


class SourceComposer:
    """Stateful latest-fact cache with deterministic arbitration.

    Per-source stale observations are ignored. Global duplicate IDs are
    idempotent. Cross-source arbitration uses observation timestamps, so a late
    older primary result cannot silently overwrite a newer authorized fallback.
    """

    def __init__(self, account_id: str, policy: SourceCompositionPolicy) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        self.account_id = account_id
        self.policy = policy
        self._latest_by_source: dict[str, SourceObservation] = {}
        self._seen_observation_ids: set[str] = set()

    def snapshot(self) -> ComposerSnapshot:
        return ComposerSnapshot(
            account_id=self.account_id,
            latest_by_source=tuple(
                sorted(self._latest_by_source.values(), key=lambda item: item.source_id)
            ),
            seen_observation_ids=frozenset(self._seen_observation_ids),
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ComposerSnapshot,
        policy: SourceCompositionPolicy,
    ) -> "SourceComposer":
        composer = cls(snapshot.account_id, policy)
        composer._seen_observation_ids = set(snapshot.seen_observation_ids)
        for observation in snapshot.latest_by_source:
            if observation.account_id != snapshot.account_id:
                raise ValueError("snapshot contains another account")
            if observation.source_id not in policy.roles:
                raise ValueError("snapshot contains source absent from policy")
            composer._latest_by_source[observation.source_id] = observation
        return composer

    def ingest(self, observation: SourceObservation) -> IngestResult:
        if observation.account_id != self.account_id:
            raise ValueError("observation account_id does not match composer")
        if observation.source_id not in self.policy.roles:
            raise ValueError("observation source_id is not configured")

        if observation.observation_id in self._seen_observation_ids:
            return IngestResult(False, True, False, observation.source_id)

        self._seen_observation_ids.add(observation.observation_id)
        current = self._latest_by_source.get(observation.source_id)
        if current is not None and observation.observed_at < current.observed_at:
            return IngestResult(False, False, True, observation.source_id)

        if current is None or (observation.observed_at, observation.observation_id) >= (
            current.observed_at,
            current.observation_id,
        ):
            self._latest_by_source[observation.source_id] = observation

        return IngestResult(True, False, False, observation.source_id)

    def ingest_many(self, observations: list[SourceObservation]) -> list[IngestResult]:
        return [self.ingest(observation) for observation in observations]

    def compose(self) -> ComposedObservation:
        facts = tuple(self._latest_by_source.values())
        if not facts:
            return ComposedObservation(
                account_id=self.account_id,
                status=CanonicalStatus.UNKNOWN,
                reason=CompositionReason.NO_DECISIVE_STATUS,
                observed_at=None,
                status_sources=(),
                conflict_sources=(),
                room_id=None,
                title=None,
                live_url=None,
                source_started_at=None,
                metadata_provenance={},
            )

        latest_any_at = max(item.observed_at for item in facts)
        claims = [item for item in facts if self._authorized_status(item) is not None]
        fresh_claims = [
            item
            for item in claims
            if (latest_any_at - item.observed_at).total_seconds()
            <= self.policy.max_fallback_lag_seconds
        ]

        status, reason, status_sources, conflict_sources, status_at = self._resolve_status(
            fresh_claims,
            latest_any_at,
        )
        metadata, provenance = self._resolve_metadata(facts, latest_any_at)

        return ComposedObservation(
            account_id=self.account_id,
            status=status,
            reason=reason,
            observed_at=status_at or latest_any_at,
            status_sources=status_sources,
            conflict_sources=conflict_sources,
            room_id=metadata["room_id"],
            title=metadata["title"],
            live_url=metadata["live_url"],
            source_started_at=metadata["source_started_at"],
            metadata_provenance=provenance,
        )

    def _authorized_status(self, observation: SourceObservation) -> CanonicalStatus | None:
        role = self.policy.roles[observation.source_id]
        if role in (SourceRole.PRIMARY_STATUS, SourceRole.FULL_STATUS):
            if observation.status in (CanonicalStatus.LIVE, CanonicalStatus.OFFLINE):
                return observation.status
            return None
        if role is SourceRole.POSITIVE_STATUS and observation.status is CanonicalStatus.LIVE:
            return CanonicalStatus.LIVE
        return None

    def _resolve_status(
        self,
        claims: list[SourceObservation],
        latest_any_at: datetime,
    ) -> tuple[
        CanonicalStatus,
        CompositionReason,
        tuple[str, ...],
        tuple[str, ...],
        datetime | None,
    ]:
        if not claims:
            return (
                CanonicalStatus.UNKNOWN,
                CompositionReason.NO_DECISIVE_STATUS,
                (),
                (),
                latest_any_at,
            )

        primary = self._latest_by_source.get(self.policy.primary_source)
        primary_status = self._authorized_status(primary) if primary is not None else None
        primary_fresh = (
            primary is not None
            and primary_status is not None
            and (latest_any_at - primary.observed_at).total_seconds()
            <= self.policy.max_fallback_lag_seconds
        )

        newest_claim_at = max(item.observed_at for item in claims)
        newest_claims = [item for item in claims if item.observed_at == newest_claim_at]
        newest_statuses = {self._authorized_status(item) for item in newest_claims}
        if len(newest_statuses) > 1:
            sources = tuple(sorted(item.source_id for item in newest_claims))
            return CanonicalStatus.UNKNOWN, CompositionReason.CONFLICT, (), sources, newest_claim_at

        if primary_fresh:
            assert primary is not None and primary_status is not None
            opposing = [
                item
                for item in claims
                if self._authorized_status(item) is not primary_status
                and abs((item.observed_at - primary.observed_at).total_seconds())
                <= self.policy.conflict_window_seconds
            ]
            if opposing:
                sources = tuple(sorted({primary.source_id, *(item.source_id for item in opposing)}))
                conflict_at = max([primary.observed_at, *(item.observed_at for item in opposing)])
                return CanonicalStatus.UNKNOWN, CompositionReason.CONFLICT, (), sources, conflict_at

            supporters = tuple(
                sorted(
                    item.source_id
                    for item in claims
                    if self._authorized_status(item) is primary_status
                )
            )
            return primary_status, CompositionReason.PRIMARY, supporters, (), primary.observed_at

        newest_status = self._authorized_status(newest_claims[0])
        assert newest_status is not None
        opposing = [
            item
            for item in claims
            if self._authorized_status(item) is not newest_status
            and abs((item.observed_at - newest_claim_at).total_seconds())
            <= self.policy.conflict_window_seconds
        ]
        if opposing:
            sources = tuple(
                sorted({*(item.source_id for item in newest_claims), *(item.source_id for item in opposing)})
            )
            return CanonicalStatus.UNKNOWN, CompositionReason.CONFLICT, (), sources, newest_claim_at

        supporters = tuple(
            sorted(item.source_id for item in claims if self._authorized_status(item) is newest_status)
        )
        newest_roles = {self.policy.roles[item.source_id] for item in newest_claims}
        reason = (
            CompositionReason.POSITIVE_FALLBACK
            if newest_status is CanonicalStatus.LIVE
            and SourceRole.POSITIVE_STATUS in newest_roles
            else CompositionReason.FULL_FALLBACK
        )
        return newest_status, reason, supporters, (), newest_claim_at

    def _resolve_metadata(
        self,
        facts: tuple[SourceObservation, ...],
        latest_any_at: datetime,
    ) -> tuple[dict[str, object | None], dict[str, FieldProvenance]]:
        by_source = {item.source_id: item for item in facts}
        values: dict[str, object | None] = {
            "room_id": None,
            "title": None,
            "live_url": None,
            "source_started_at": None,
        }
        provenance: dict[str, FieldProvenance] = {}

        for field_name in values:
            for source_id in self.policy.metadata_priority:
                item = by_source.get(source_id)
                if item is None:
                    continue
                if (latest_any_at - item.observed_at).total_seconds() > self.policy.max_metadata_lag_seconds:
                    continue
                value = getattr(item, field_name)
                if value is None or value == "":
                    continue
                values[field_name] = value
                provenance[field_name] = FieldProvenance(
                    source_id=source_id,
                    observation_id=item.observation_id,
                    observed_at=item.observed_at,
                )
                break

        return values, provenance
