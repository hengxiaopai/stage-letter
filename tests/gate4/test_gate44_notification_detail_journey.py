from __future__ import annotations

from pathlib import Path

import pytest

from stage_letter.domain.notification_history import AnchorDetailTarget


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


def _read(relative_path: str) -> str:
    return (MINIAPP / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("anchor_id", ("", "0", "-1", "1.0", "abc", "1&debug=1"))
def test_detail_target_rejects_non_positive_or_non_canonical_identity(anchor_id: str) -> None:
    with pytest.raises(ValueError, match="anchor_id"):
        AnchorDetailTarget(anchor_id)


def test_history_repository_routes_by_formal_creator_identity() -> None:
    repository = (
        ROOT
        / "stage_letter"
        / "infrastructure"
        / "db"
        / "repositories"
        / "notification.py"
    ).read_text(encoding="utf-8")
    history_mapping = repository[repository.index("def _to_history_entry") :]

    assert "anchor_id = account.creator_id" in history_mapping
    assert "account.legacy_anchor_id or account.creator_id" not in history_mapping


def test_profile_accepts_only_exact_server_detail_contract() -> None:
    source = _read("pages/profile/index.js")

    assert "DETAIL_PAGE_RE" in source
    assert "canonicalDetailPage" in source
    assert "page !== expected" in source
    assert ".startsWith('pages/detail/index?id=')" not in source
    assert "通知链接无效" in source


def test_detail_page_rejects_invalid_id_before_api_read() -> None:
    source = _read("pages/detail/index.js")
    on_load = source[source.index("onLoad(options)") : source.index("async load()")]

    assert "POSITIVE_ID_RE" in source
    assert "主播信息无效" in on_load
    assert on_load.index("POSITIVE_ID_RE.test") < on_load.index("this.load()")


def test_history_row_remains_user_driven_navigation() -> None:
    markup = _read("pages/profile/index.wxml")

    assert 'bindtap="onHistoryTap"' in markup
    assert 'data-page="{{item.page}}"' in markup


def test_initial_history_request_omits_keyset_cursor() -> None:
    source = _read("services/notifications.js")

    assert "cursor = null" in source
    assert "cursor = 0" not in source
