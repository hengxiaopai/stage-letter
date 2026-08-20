from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.admin_security import AdminActor
from api.routers.admin import render_admin_inquiry_page
from api.services.admin_inquiry import MAX_PAGE_SIZE, _cursor, _limit


def test_admin_inquiry_pagination_is_bounded_and_opaque_to_the_browser() -> None:
    assert _limit(MAX_PAGE_SIZE) == MAX_PAGE_SIZE
    assert _cursor("42") == 42
    for invalid in ("0", "-1", "not-an-id"):
        with pytest.raises(HTTPException) as exc:
            _cursor(invalid)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        _limit(MAX_PAGE_SIZE + 1)


def test_admin_inquiry_page_escapes_values_and_excludes_sensitive_fields() -> None:
    html = render_admin_inquiry_page(
        actor=AdminActor(username="<operator>"),
        users={"items": [{"id": 1, "created_at": None, "last_active_at": None, "subscription_count": 2}]},
        subscriptions={"items": [{"id": 2, "user_id": 1, "creator_id": 3, "display_name": "<anchor>", "platform": "bilibili", "notify_enabled": True, "created_at": None}]},
        deliveries={"items": [{"id": 4, "user_id": 1, "channel": "IN_APP", "state": "SENT", "attempt": 1, "error_code": None, "sent_at": None, "created_at": None}]},
    )

    assert "&lt;operator&gt;" in html
    assert "&lt;anchor&gt;" in html
    assert "不展示 openid、模板、canonical URL 或原始错误文本" in html


def test_admin_inquiry_routes_are_protected_and_read_only() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    router = (root / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    service = (root / "api" / "services" / "admin_inquiry.py").read_text(encoding="utf-8")

    for route in ('"/admin/users"', '"/admin/subscriptions"', '"/admin/deliveries"', '"/admin/inquiry"'):
        assert route in router
    assert router.count("Depends(require_admin)") >= 4
    assert "error_message" not in service
    assert ".openid" not in service
    assert "canonical_url" not in service
