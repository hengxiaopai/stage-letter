from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINIAPP = ROOT / "miniapp"


def test_featured_live_uses_the_materialized_meta_field_and_detail_cta() -> None:
    markup = (MINIAPP / "pages" / "home" / "index.wxml").read_text(encoding="utf-8")
    script = (MINIAPP / "pages" / "home" / "index.js").read_text(encoding="utf-8")

    assert "featuredLive.meta" in markup
    assert "featuredLive.liveMeta" not in markup
    assert "查看详情" in markup
    assert "进入直播间" not in markup
    assert "meta: showTime" in script


def test_ambiguous_delivery_is_neither_failed_nor_retrying() -> None:
    script = (MINIAPP / "pages" / "messages" / "index.js").read_text(encoding="utf-8")
    stylesheet = (MINIAPP / "pages" / "messages" / "index.wxss").read_text(encoding="utf-8")

    ambiguous_block = script.split("state === 'AMBIGUOUS'", 1)[1].split("return {", 1)[0]
    assert "kind = 'ambiguous'" in ambiguous_block
    assert "label = '结果待确认'" in ambiguous_block
    assert "detail = '投递结果暂时无法确认'" in ambiguous_block
    assert "kind = 'failed'" not in ambiguous_block
    assert "kind = 'retry'" not in ambiguous_block
    assert "{ label: '待确认', value: 'ambiguous' }" in script
    assert ".delivery-ambiguous" in stylesheet


def test_v23_tabbar_tokens_and_labels_match_the_contract() -> None:
    app_json = json.loads((MINIAPP / "app.json").read_text(encoding="utf-8"))
    tabbar = app_json["tabBar"]

    assert tabbar["color"] == "#7C8AA5"
    assert tabbar["selectedColor"] == "#2F6BFF"
    assert [item["text"] for item in tabbar["list"]] == ["首页", "发现", "消息", "我的"]
