"""Regression coverage for the asynchronous manual refresh endpoint."""
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "api" / "routers" / "lives.py").read_text(
    encoding="utf-8"
)


def test_active_read_endpoint_never_returns_refresh_cooldown_payload() -> None:
    active_source = SOURCE.split("async def lives_active", 1)[1].split(
        '@router.post("/lives/refresh"', 1
    )[0]
    assert "_REFRESH_COOLDOWNS" not in active_source
    assert "RefreshAcceptedResponse" not in active_source


def test_refresh_endpoint_initializes_and_enforces_its_own_cooldown() -> None:
    refresh_source = SOURCE.split('@router.post("/lives/refresh"', 1)[1]
    assert "now = datetime.now(timezone.utc)" in refresh_source
    assert "existing_cooldown = _REFRESH_COOLDOWNS.get(openid)" in refresh_source
    assert 'status="cooldown"' in refresh_source
    assert "return RefreshAcceptedResponse(" in refresh_source
