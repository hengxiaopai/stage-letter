"""Audited Gate 5.2 platform-level operational controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import AdminPlatformAction, PlatformHealth, PlatformHealthState


MANAGEABLE_PLATFORMS = frozenset({"bilibili", "douyin", "douyu", "huya"})


class PlatformControlAction(str, Enum):
    DISABLE = "DISABLE"
    ENABLE = "ENABLE"


@dataclass(frozen=True)
class PlatformControlResult:
    platform: str
    action: PlatformControlAction
    prior_state: str | None
    resulting_state: str
    acted_at: datetime


def _target_state(action: PlatformControlAction) -> str:
    if action is PlatformControlAction.DISABLE:
        return PlatformHealthState.DISABLED.value
    # A manual enable is a cautious half-open recovery. A successful probe is
    # still required before the circuit breaker returns to HEALTHY.
    return PlatformHealthState.DEGRADED.value


def _validate_platform(platform: str) -> str:
    normalized = platform.strip().lower()
    if normalized not in MANAGEABLE_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="managed platform not found",
        )
    return normalized


async def apply_platform_control(
    db: AsyncSession,
    *,
    actor_username: str,
    platform: str,
    action: PlatformControlAction,
) -> PlatformControlResult:
    """Apply exactly one audited health-state change in the request transaction."""

    platform = _validate_platform(platform)
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(PlatformHealth)
            .where(PlatformHealth.platform == platform)
            .with_for_update()
        )
    ).scalar_one_or_none()
    prior_state = None if row is None else row.state
    resulting_state = _target_state(action)
    if row is None:
        row = PlatformHealth(
            platform=platform,
            state=resulting_state,
            consecutive_failures=0,
            error_count_24h=0,
            success_count_24h=0,
            updated_at=now,
        )
        db.add(row)
    else:
        row.state = resulting_state
        row.updated_at = now
        if action is PlatformControlAction.ENABLE:
            row.consecutive_failures = 0

    db.add(
        AdminPlatformAction(
            actor_username=actor_username,
            platform=platform,
            requested_action=action.value,
            prior_state=prior_state,
            resulting_state=resulting_state,
            created_at=now,
        )
    )
    await db.commit()
    return PlatformControlResult(
        platform=platform,
        action=action,
        prior_state=prior_state,
        resulting_state=resulting_state,
        acted_at=now,
    )
