"""Gate 2 Detection Engine formal boundary."""

from .contracts import PlatformHealthState, PollingTier
from .lease import (
    DetectionLeaseAcquireResult,
    DetectionLeasePolicy,
    DetectionProbeLease,
)

__all__ = [
    "DetectionLeaseAcquireResult",
    "DetectionLeasePolicy",
    "DetectionProbeLease",
    "PlatformHealthState",
    "PollingTier",
]
