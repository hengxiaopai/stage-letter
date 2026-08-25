"""Current-live-state timeout guarantees for the Mini Program."""
from datetime import datetime, timedelta, timezone

from core.live_state import CONFIRM_TIMEOUT_S, current_live_state


def test_stale_status_exits_confirming_after_short_bounded_window() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    state = current_live_state(
        "OFFLINE",
        now - timedelta(seconds=CONFIRM_TIMEOUT_S + 1),
        now=now,
    )

    assert CONFIRM_TIMEOUT_S == 75
    assert state["state"] == "UNKNOWN"


def test_never_successful_online_probe_cannot_confirm_forever() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    state = current_live_state(
        "ONLINE",
        None,
        heartbeat_at=now - timedelta(seconds=CONFIRM_TIMEOUT_S + 1),
        now=now,
    )

    assert state["state"] == "UNKNOWN"
    assert state["freshness"] == "stale"


def test_recent_unconfirmed_online_probe_remains_confirming() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    state = current_live_state(
        "ONLINE",
        None,
        heartbeat_at=now - timedelta(seconds=20),
        now=now,
    )

    assert state["state"] == "CONFIRMING"


def test_stale_but_recently_confirmed_offline_does_not_flash_confirming() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    state = current_live_state(
        "OFFLINE",
        now - timedelta(seconds=50),
        now=now,
    )

    assert state["state"] == "OFFLINE"
    assert state["freshness"] == "stale"
