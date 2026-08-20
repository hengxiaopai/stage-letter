from __future__ import annotations

from pathlib import Path

from api.admin_security import AdminActor
from api.routers.admin import render_admin_metrics_page
from api.services.admin_metrics import KNOWN_CHANNELS, bounded_label


ROOT = Path(__file__).resolve().parents[2]


def test_metric_labels_are_fixed_and_unknown_values_are_collapsed() -> None:
    assert bounded_label("IN_APP", KNOWN_CHANNELS) == "IN_APP"
    assert bounded_label("arbitrary provider response", KNOWN_CHANNELS) == "OTHER"
    assert bounded_label(None, KNOWN_CHANNELS) == "OTHER"


def test_metrics_page_escapes_values_and_describes_the_redaction_boundary() -> None:
    html = render_admin_metrics_page(
        actor=AdminActor(username="operator<script>"),
        metrics={
            "platform_health_24h": [{"platform": "OTHER", "success_count_24h": 2, "error_count_24h": 1}],
            "deliveries_by_channel_state": [{"channel": "IN_APP", "state": "SENT", "count": 3}],
            "delivery_errors_by_code": [{"error_code": "OTHER", "count": 1}],
        },
    )

    assert "operator&lt;script&gt;" in html
    assert "原始错误文本" in html
    assert "OTHER" in html


def test_metrics_routes_are_protected_read_only_and_use_bounded_labels() -> None:
    router = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    service = (ROOT / "api" / "services" / "admin_metrics.py").read_text(encoding="utf-8")

    assert '"/admin/metrics"' in router
    assert '"/admin/metrics/page"' in router
    assert router.count("Depends(require_admin)") >= 6
    assert "case(" in service
    assert 'else_="OTHER"' in service
    for forbidden in ("openid", "display_name", "canonical_url", "error_message"):
        assert forbidden not in service.lower()
