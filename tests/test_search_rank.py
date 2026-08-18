"""search_core rank 回归测试 — 2026-08-14 排序修复后固化。

运行: python -m tests.test_search_rank
覆盖:
  1. 僵尸号 EXACT(<1000粉) → 高粉 CONTAINS 升级 PREFIX, 105万粉第一
  2. 真实 EXACT(≥1000粉) 绝对优先, 300万粉 PREFIX 不得反超
  3. 无 EXACT + 高粉 CONTAINS → 升级
  4. CONTAINS <10万粉 不升级
  5. EXACT 800粉(僵尸) → 高粉升级压过
  6. 非僵尸 EXACT 5000粉 → 正常拿权重, 仍第一
  7. 真实全池(含 PREFIX/CONTAINS 混合) 顺序
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services import search_core as sc


def run(cands, kw):
    passed = sc.relevance_filter(cands, kw)
    return sc.rank_items(sc.deduplicate(passed), kw)


def test_zombie_exact_loses_to_high_fan():
    r = run([
        {"platform": "bilibili", "user_id": "1", "display_name": "四五六七洄", "fans": 8360},
        {"platform": "douyin", "user_id": "4", "display_name": "𝑿.四五六🍉", "fans": 1055909},
        {"platform": "bilibili", "user_id": "5", "display_name": "四五六", "fans": 111},
    ], "四五六")
    assert r[0]["display_name"] == "𝑿.四五六🍉", r[0]
    assert r[0]["match_type"] == sc.PREFIX, "高粉 CONTAINS 应升级 PREFIX"
    assert r[0]["match_score"] == sc.MATCH_SCORES[sc.PREFIX], "match_score 应同步"


def test_real_exact_absolute_priority():
    r = run([
        {"platform": "huya", "user_id": "a", "display_name": "阿哲", "fans": 500000},
        {"platform": "douyin", "user_id": "b", "display_name": "阿哲哥哥的粉丝团", "fans": 3000000},
    ], "阿哲")
    assert r[0]["display_name"] == "阿哲", r[0]
    assert r[1]["match_type"] == sc.PREFIX, "粉丝团是原生 PREFIX 不升级(非 CONTAINS)"


def test_no_exact_high_fan_upgrade():
    r = run([
        {"platform": "douyin", "user_id": "c", "display_name": "某某四五六直播", "fans": 2000000},
        {"platform": "bilibili", "user_id": "d", "display_name": "四五六小助手", "fans": 90000},
    ], "四五六")
    assert r[0]["display_name"] == "某某四五六直播", r[0]


def test_contains_under_100k_no_upgrade():
    r = run([
        {"platform": "bilibili", "user_id": "e", "display_name": "陆沉四五六切片", "fans": 5000},
        {"platform": "douyin", "user_id": "f", "display_name": "是个四五六号", "fans": 90000},
    ], "四五六")
    assert all(it["match_type"] == sc.CONTAINS for it in r), [it["match_type"] for it in r]


def test_800_fan_exact_is_zombie():
    r = run([
        {"platform": "bilibili", "user_id": "g", "display_name": "四五六", "fans": 800},
        {"platform": "douyin", "user_id": "h", "display_name": "四五六大家庭", "fans": 5000000},
    ], "四五六")
    assert r[0]["display_name"] == "四五六大家庭", r[0]


def test_5000_fan_exact_not_zombie():
    r = run([
        {"platform": "bilibili", "user_id": "i", "display_name": "四五六", "fans": 5000},
        {"platform": "douyin", "user_id": "j", "display_name": "四五六主播", "fans": 500000},
    ], "四五六")
    assert r[0]["display_name"] == "四五六", r[0]


def test_full_pool():
    r = run([
        {"platform": "bilibili", "user_id": "1", "display_name": "四五六七洄", "fans": 8360},
        {"platform": "bilibili", "user_id": "2", "display_name": "四五六默麒灵", "fans": 4434},
        {"platform": "douyin", "user_id": "4", "display_name": "𝑿.四五六🍉", "fans": 1055909},
        {"platform": "bilibili", "user_id": "5", "display_name": "四五六", "fans": 111},
        {"platform": "bilibili", "user_id": "6", "display_name": "狐一二三四五六七八九", "fans": 4513},
        {"platform": "bilibili", "user_id": "7", "display_name": "刺客四五六", "fans": 4199},
    ], "四五六")
    names = [it["display_name"] for it in r]
    assert names[0] == "𝑿.四五六🍉", names
    assert names[1] == "四五六", names


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"ALL {len(tests)} TESTS PASSED")
