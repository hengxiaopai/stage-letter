from __future__ import annotations

from pathlib import Path

import pytest

from api.routers import auth
from core.models import User


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


class _Result:
    def __init__(self, user: User) -> None:
        self._user = user

    def scalar_one_or_none(self) -> User:
        return self._user


class _ExistingUserDb:
    def __init__(self, user: User) -> None:
        self.user = user

    async def execute(self, _statement) -> _Result:
        return _Result(self.user)


def _read(relative_path: str) -> str:
    return (MINIAPP / relative_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_login_returns_server_configured_public_template_id(monkeypatch) -> None:
    user = User(id=43, openid="wx-openid-43")

    class _Client:
        def code2session(self, _code: str) -> dict[str, str]:
            return {"openid": "wx-openid-43"}

    monkeypatch.setattr(auth, "get_wechat_client", lambda: _Client())
    monkeypatch.setattr(auth.settings, "wx_template_live_start", "configured-template")

    response = await auth.login(
        auth.LoginRequest(code="fresh-code"),
        _ExistingUserDb(user),  # type: ignore[arg-type]
    )

    assert response.live_start_template_id == "configured-template"


def test_client_keeps_template_from_login_in_one_app_config_source() -> None:
    auth_source = _read("services/auth.js")
    app_source = _read("app.js")
    assert "resolve(data)" in auth_source
    assert "liveStartTemplateId: null" in app_source
    assert "session.live_start_template_id" in app_source


def test_pages_do_not_duplicate_literal_template_configuration() -> None:
    add_page = _read("pages/add/index.js")
    profile_page = _read("pages/profile/index.js")
    for source in (add_page, profile_page):
        assert "liveStartTemplateId" in source
        assert "tmplIds: [templateId]" in source
        assert "VehDuOW2xRXubcWgFvcgnFnp42wdA3uesHpjfmBP-Cs" not in source


def test_permission_decision_is_recorded_but_never_blocks_subscription() -> None:
    source = _read("pages/add/index.js")
    flow = source[source.index("async confirmSubscribe") :]
    assert "if (res)" in flow
    assert "await requestGrant(openid, res)" in flow
    assert "await subscribe(" in flow
    assert "if (acceptCount === 0)" not in flow
    assert "if (!res)" not in flow
    assert "订阅成功，已启用站内提醒" in flow


def test_permission_request_remains_inside_user_driven_page_handlers() -> None:
    app_source = _read("app.js")
    add_page = _read("pages/add/index.js")
    profile_page = _read("pages/profile/index.js")
    assert "requestSubscribeMessage" not in app_source
    assert add_page.index("async confirmSubscribe") < add_page.index("wx.requestSubscribeMessage")
    assert profile_page.index("async onTopUp") < profile_page.index("wx.requestSubscribeMessage")


def test_missing_template_still_creates_in_app_capable_subscription() -> None:
    source = _read("pages/add/index.js")
    flow = source[source.index("async confirmSubscribe") :]
    assert "if (templateId)" in flow
    assert "await subscribe(" in flow
    assert "订阅成功，已启用站内提醒" in flow


def test_gate3_fallback_boundary_remains_the_reason_permission_is_optional() -> None:
    gate3 = (ROOT / "GATE-3.md").read_text(encoding="utf-8")
    gate4 = (ROOT / "GATE-4.md").read_text(encoding="utf-8")
    assert "Missing or exhausted grant" in gate3
    assert "IN_APP" in gate3
    assert "Permission is user-driven" in gate4


def test_subscription_write_keeps_gate1_formal_follow_bridge() -> None:
    router = (ROOT / "api" / "routers" / "subscriptions.py").read_text(encoding="utf-8")
    models = (ROOT / "core" / "models.py").read_text(encoding="utf-8")

    assert "creator_id = Column(BigInteger, nullable=False)" in models
    assert "creator_id=anchor.id" in router
    assert "await _ensure_formal_creator(" in router
    assert "await _ensure_formal_follow(" in router
    assert "FollowModel(" in router
    assert "NotificationPreferenceModel(" in router
