"""Pure scheduling policy for Gate 2.1 detection due selection.

Polling cadence is operational metadata only. It decides when an enabled account
may be probed; it never creates live truth or notification state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from stage_letter.detection.contracts import PollingTier


@dataclass(frozen=True)
class DetectionCadencePolicy:
    hot_seconds: int = 30
    warm_seconds: int = 60
    cold_seconds: int = 300

    def __post_init__(self) -> None:
        if min(self.hot_seconds, self.warm_seconds, self.cold_seconds) <= 0:
            raise ValueError("detection cadence values must be positive")
        if not self.hot_seconds <= self.warm_seconds <= self.cold_seconds:
            raise ValueError("detection cadence must satisfy hot <= warm <= cold")

    def interval(self, tier: PollingTier) -> timedelta:
        seconds = {
            PollingTier.HOT: self.hot_seconds,
            PollingTier.WARM: self.warm_seconds,
            PollingTier.COLD: self.cold_seconds,
        }[tier]
        return timedelta(seconds=seconds)


def normalize_polling_tier(raw: str | None) -> PollingTier:
    """Normalize legacy operational data without increasing provider pressure.

    Legacy NULL/blank values mean "not explicitly classified" and therefore use
    WARM, the accepted default. A non-blank unknown value is treated as COLD so
    corrupted metadata cannot accidentally increase provider request rate.
    """

    if raw is None or not raw.strip():
        return PollingTier.WARM
    try:
        return PollingTier(raw.strip().lower())
    except ValueError:
        return PollingTier.COLD


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduling timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def due_at(
    *,
    tier: PollingTier,
    last_probe_at: datetime | None,
    policy: DetectionCadencePolicy,
) -> datetime | None:
    """Return the next eligible instant; None means never-probed and due now."""

    if last_probe_at is None:
        return None
    return _utc(last_probe_at) + policy.interval(tier)


def is_due(
    *,
    now: datetime,
    tier: PollingTier,
    last_probe_at: datetime | None,
    policy: DetectionCadencePolicy,
) -> bool:
    next_at = due_at(tier=tier, last_probe_at=last_probe_at, policy=policy)
    return next_at is None or _utc(now) >= next_at
