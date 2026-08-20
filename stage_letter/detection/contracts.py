"""Stable operational vocabulary for Gate 2 Detection Engine.

Detection metadata controls when/how probes run. It is deliberately separate
from canonical live truth: these values must never by themselves create LIVE,
OFFLINE, LiveSession, or LiveEvent facts.
"""
from __future__ import annotations

from enum import Enum


class PollingTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class PlatformHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
