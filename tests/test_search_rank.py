"""search_core 分层排序回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services import search_core as sc


def run(candidates: list[dict], keyword: str) -> list[dict]:
    matched = sc.relevance_filter(candidates, keyword)
    return sc.rank_items(sc.deduplicate(matched), keyword)


def test_exact_remains_ahead_of_high_fan_prefix() -> None:
    results = run([
        {"platform": "bilibili", "user_id": "1", "display_name": "大司马", "fans": 1117},
        {"platform": "douyin", "user_id": "2", "display_name": "大司马解说", "fans": 14_773_000},
    ], "大司马")
    assert [item["display_name"] for item in results] == ["大司马", "大司马解说"]


def test_same_match_level_live_is_ahead_of_fans() -> None:
    results = run([
        {"platform": "douyin", "user_id": "1", "display_name": "大司马直播", "fans": 2_000_000, "is_live": False},
        {"platform": "bilibili", "user_id": "2", "display_name": "大司马小助手", "fans": 90_000, "live_state": "LIVE"},
    ], "大司马")
    assert results[0]["display_name"] == "大司马小助手"


def test_same_match_and_live_state_uses_fans() -> None:
    results = run([
        {"platform": "douyin", "user_id": "1", "display_name": "大司马直播", "fans": 2_000_000},
        {"platform": "bilibili", "user_id": "2", "display_name": "大司马小助手", "fans": 90_000},
    ], "大司马")
    assert results[0]["display_name"] == "大司马直播"


def test_subscribed_stays_ahead_of_unsubscribed_same_match() -> None:
    results = run([
        {"platform": "bilibili", "user_id": "1", "display_name": "大司马直播", "fans": 5_000, "is_subscribed": True},
        {"platform": "douyin", "user_id": "2", "display_name": "大司马主播", "fans": 500_000},
    ], "大司马")
    assert results[0]["user_id"] == "1"


def test_exact_low_fan_is_not_demoted() -> None:
    results = run([
        {"platform": "bilibili", "user_id": "1", "display_name": "大司马", "fans": 8},
        {"platform": "douyin", "user_id": "2", "display_name": "大司马大家庭", "fans": 5_000_000, "is_live": True},
    ], "大司马")
    assert results[0]["display_name"] == "大司马"
