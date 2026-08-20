from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


def _read(relative_path: str) -> str:
    return (MINIAPP / relative_path).read_text(encoding="utf-8")


def test_api_errors_preserve_http_status_for_page_reconciliation() -> None:
    source = _read("services/api.js")
    assert "class ApiError extends Error" in source
    assert "this.statusCode = statusCode" in source
    assert "new ApiError" in source
    assert "module.exports = { request, ApiError }" in source


def test_profile_exposes_load_failure_and_retry_instead_of_empty_history() -> None:
    script = _read("pages/profile/index.js")
    template = _read("pages/profile/index.wxml")
    assert "error: null" in script
    assert "error: err.message" in script
    assert "retryLoad()" in script
    assert 'wx:elif="{{error}}"' in template
    assert 'bindtap="retryLoad"' in template


def test_detail_unknown_state_never_renders_confirmed_offline_copy() -> None:
    template = _read("pages/detail/index.wxml")
    assert 'wx:elif="{{liveLabel === \'未开播\'}}"' in template
    assert "直播状态暂时无法确认" in template
    assert "系统会持续重试" in template


def test_subscription_delete_uses_structured_404_and_formal_live_flag() -> None:
    source = _read("pages/subscriptions/index.js")
    assert "err.statusCode === 404" in source
    assert "subs.filter((s) => s.isLiveFlag).length" in source
    assert "err.message.includes('404')" not in source


def test_retry_handlers_clear_stale_errors_before_loading_again() -> None:
    pages = {
        "home": "loadAll()",
        "subscriptions": "load()",
        "profile": "load()",
        "detail": "load()",
    }
    for page, call in pages.items():
        source = _read(f"pages/{page}/index.js")
        template = _read(f"pages/{page}/index.wxml")
        assert "retryLoad()" in source
        assert "loading: true, error: null" in source
        assert call in source
        assert 'bindtap="retryLoad"' in template


def test_core_refreshable_tabs_keep_pull_down_refresh_enabled() -> None:
    for page in ("home", "subscriptions", "profile"):
        manifest = _read(f"pages/{page}/index.json")
        script = _read(f"pages/{page}/index.js")
        assert '"enablePullDownRefresh": true' in manifest
        assert "onPullDownRefresh()" in script
        assert "wx.stopPullDownRefresh()" in script


def test_home_and_subscription_views_keep_unknown_separate_from_offline() -> None:
    home = _read("pages/home/index.js")
    subscriptions = _read("pages/subscriptions/index.js")
    assert "unknownList.push(row)" in home
    assert "waitList.push(row)" in home
    assert "st === 'UNKNOWN' || st === 'DEGRADED'" in home
    assert "检测失败 · 正在持续重试" in subscriptions
    report = (ROOT / "reports" / "gate42_core_page_states.md").read_text(encoding="utf-8")
    assert "Status: PASS" in report
    assert "No fake subscription or detail record" in report
