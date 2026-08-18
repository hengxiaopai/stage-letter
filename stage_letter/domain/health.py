"""Runtime source-health truth separated from admin enable/disable."""

from enum import Enum


class RuntimeHealthState(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
