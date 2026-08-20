"""Bounded, read-only operational aggregates for Gate 5.4."""
from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import NotificationDelivery, PlatformHealth


KNOWN_PLATFORMS = frozenset({"bilibili", "douyin", "douyu", "huya"})
KNOWN_CHANNELS = frozenset({"WECHAT_SUBSCRIBE", "IN_APP"})
KNOWN_DELIVERY_STATES = frozenset(
    {
        "PENDING",
        "IN_FLIGHT",
        "WAITING_RETRY",
        "WAITING_AUTH",
        "BLOCKED_CONFIG",
        "SENT",
        "FAILED_TERMINAL",
        "AMBIGUOUS",
    }
)
KNOWN_ERROR_CODES = frozenset(
    {
        "40037",
        "43101",
        "PROVIDER_OUTCOME_AMBIGUOUS",
        "CRASH_RECOVERY_AMBIGUOUS",
        "RETRY_EXHAUSTED",
        "TOKEN_UNAVAILABLE",
        "SEND_TRANSPORT_AMBIGUOUS",
    }
)


def bounded_label(value: str | None, allowed: frozenset[str]) -> str:
    """Keep every aggregate dimension within a small, documented vocabulary."""

    return value if value in allowed else "OTHER"


def _label(column, allowed: frozenset[str], name: str):
    return case((column.in_(allowed), column), else_="OTHER").label(name)


async def build_admin_metrics(db: AsyncSession) -> dict:
    """Return compact aggregate rows only; never return delivery/user entities."""

    platform = _label(PlatformHealth.platform, KNOWN_PLATFORMS, "platform")
    channel = _label(NotificationDelivery.channel, KNOWN_CHANNELS, "channel")
    delivery_state = _label(NotificationDelivery.state, KNOWN_DELIVERY_STATES, "state")
    error_code = _label(NotificationDelivery.error_code, KNOWN_ERROR_CODES, "error_code")

    platform_rows = (
        await db.execute(
            select(
                platform,
                func.sum(PlatformHealth.success_count_24h).label("success_count_24h"),
                func.sum(PlatformHealth.error_count_24h).label("error_count_24h"),
            ).group_by(platform)
        )
    ).mappings().all()
    delivery_rows = (
        await db.execute(
            select(channel, delivery_state, func.count(NotificationDelivery.id).label("count"))
            .group_by(channel, delivery_state)
            .order_by(channel, delivery_state)
        )
    ).mappings().all()
    error_rows = (
        await db.execute(
            select(error_code, func.count(NotificationDelivery.id).label("count"))
            .where(NotificationDelivery.error_code.is_not(None))
            .group_by(error_code)
            .order_by(error_code)
        )
    ).mappings().all()

    return {
        "platform_health_24h": [dict(row) for row in platform_rows],
        "deliveries_by_channel_state": [dict(row) for row in delivery_rows],
        "delivery_errors_by_code": [dict(row) for row in error_rows],
    }
