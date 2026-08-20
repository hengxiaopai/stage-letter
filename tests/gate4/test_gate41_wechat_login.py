from __future__ import annotations

from pathlib import Path

import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from api.routers import auth
from api.services.wechat import WeChatError
from core.models import User


ROOT = Path(__file__).resolve().parents[2]


class _Result:
    def __init__(self, user: User | None) -> None:
        self._user = user

    def scalar_one_or_none(self) -> User | None:
        return self._user


class _ExistingUserDb:
    def __init__(self, user: User) -> None:
        self.user = user
        self.execute_count = 0

    async def execute(self, _statement) -> _Result:
        self.execute_count += 1
        return _Result(self.user)


class _NewUserDb:
    def __init__(self) -> None:
        self.added: User | None = None
        self.commit_count = 0

    async def execute(self, _statement) -> _Result:
        return _Result(None)

    def add(self, user: User) -> None:
        self.added = user

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, user: User) -> None:
        user.id = 84


def test_client_always_uses_wx_login_without_fixed_openid_or_storage() -> None:
    source = (ROOT / "miniapp" / "services" / "auth.js").read_text(encoding="utf-8")
    assert "DEV_OPENID" not in source
    assert "wx.login" in source
    assert "request('/auth/login'" in source
    assert source.index("wx.login") < source.index("request('/auth/login'")
    assert "wx.setStorage" not in source


def test_app_keeps_one_login_in_flight_and_allows_retry_after_failure() -> None:
    source = (ROOT / "miniapp" / "app.js").read_text(encoding="utf-8")
    assert "if (this.globalData.openid)" in source
    assert "if (this.loginPromise)" in source
    assert "this.loginPromise = null" in source
    assert "loginState: 'authenticated'" in source
    assert "loginState: 'failed'" in source


def test_login_request_rejects_blank_or_oversized_code() -> None:
    for code in ("", "   ", "x" * 129):
        with pytest.raises(ValidationError):
            auth.LoginRequest(code=code)


@pytest.mark.asyncio
async def test_backend_exchanges_real_code_and_reuses_existing_user(monkeypatch) -> None:
    user = User(id=42, openid="wx-openid-42", unionid="union-42")
    db = _ExistingUserDb(user)

    class _Client:
        def code2session(self, code: str) -> dict[str, str]:
            assert code == "fresh-wx-code"
            return {"openid": "wx-openid-42", "unionid": "union-42"}

    monkeypatch.setattr(auth, "get_wechat_client", lambda: _Client())

    response = await auth.login(auth.LoginRequest(code="fresh-wx-code"), db)  # type: ignore[arg-type]

    assert response.user_id == 42
    assert response.openid == "wx-openid-42"
    assert response.openid_tail == "d-42"
    assert response.is_new is False
    assert db.execute_count == 1


@pytest.mark.asyncio
async def test_backend_creates_first_time_wechat_user(monkeypatch) -> None:
    db = _NewUserDb()

    class _Client:
        def code2session(self, code: str) -> dict[str, str]:
            assert code == "first-login-code"
            return {"openid": "new-openid", "unionid": "new-unionid"}

    monkeypatch.setattr(auth, "get_wechat_client", lambda: _Client())

    response = await auth.login(auth.LoginRequest(code="first-login-code"), db)  # type: ignore[arg-type]

    assert response.user_id == 84
    assert response.openid == "new-openid"
    assert response.is_new is True
    assert db.added is not None
    assert db.added.unionid == "new-unionid"
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_missing_server_wechat_config_is_visible_not_fake_identity(monkeypatch) -> None:
    def _missing_client():
        raise RuntimeError("WX_APPID / WX_SECRET not configured")

    monkeypatch.setattr(auth, "get_wechat_client", _missing_client)

    with pytest.raises(HTTPException) as exc_info:
        await auth.login(auth.LoginRequest(code="fresh-wx-code"), object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert "配置" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rejected_code_is_visible_not_debug_fallback(monkeypatch) -> None:
    class _Client:
        def code2session(self, _code: str) -> dict:
            raise WeChatError(40029, "invalid code")

    monkeypatch.setattr(auth, "get_wechat_client", lambda: _Client())

    with pytest.raises(HTTPException) as exc_info:
        await auth.login(auth.LoginRequest(code="expired-wx-code"), object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400
    assert "失效" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_wechat_transport_failure_is_retryable_service_error(monkeypatch) -> None:
    class _Client:
        def code2session(self, _code: str) -> dict:
            request = httpx.Request("GET", "https://api.weixin.qq.com/sns/jscode2session")
            raise httpx.ConnectError("unavailable", request=request)

    monkeypatch.setattr(auth, "get_wechat_client", lambda: _Client())

    with pytest.raises(HTTPException) as exc_info:
        await auth.login(auth.LoginRequest(code="fresh-wx-code"), object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert "暂时不可用" in str(exc_info.value.detail)


def test_gate41_keeps_raw_openid_as_explicit_nonproduction_seam() -> None:
    gate4 = (ROOT / "GATE-4.md").read_text(encoding="utf-8")
    report = (ROOT / "reports" / "gate41_wechat_login.md").read_text(encoding="utf-8")
    assert "raw `openid`" in gate4
    assert "production-token limitation" in gate4
    assert "No production approval is implied" in gate4
    assert "Status: PASS" in report
    assert "login` with HTTP `200" in report
    assert "does not contain the temporary `wx.login` code" in report
