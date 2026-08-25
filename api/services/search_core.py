"""Search Core V3 — P0-10/P0-11 统一搜索聚合器。

流程(用户设计, 固定不变):
  Query → Normalize Query
    → [Local Anchor Index | Bilibili | Huya | Douyu | Douyin(登录态)]
    → Candidate Pool
    → Identity Normalize
    → Relevance Filter      (无关候选丢弃, 如虎牙赛事频道)
    → Deduplicate           (platform+platform_user_id)
    → Subscription Enrichment
    → Profile Metadata Merge (null 不覆盖)
    → Ranking               (订阅 > 匹配 > 直播状态 > 粉丝 > 稳定兜底)
    → SearchResult[]

SearchResult DTO:
  anchor_id | platform | platform_user_id | display_name | avatar |
  follower_count | is_subscribed | subscription_id | match_type | match_score |
  live_state | last_probe_at | source

Rank Model(2026-08-22, 分层排序):
  1. 已订阅
  2. 匹配级别: EXACT > NORMALIZED > PREFIX > CONTAINS > ALIAS > FUZZY
  3. 同一匹配级别内: 直播中 > 非直播/未知
  4. 同一直播状态内: 粉丝数降序
  5. 平台、用户 ID 的稳定兜底

粉丝量不再跨越匹配层级，避免高粉前缀/包含候选压过完全匹配的同名主播。
  NO_MATCH → 丢弃
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("stageletter.search.core")

# ── 匹配类型 ──
EXACT = "EXACT"
NORMALIZED = "NORMALIZED"
PREFIX = "PREFIX"
CONTAINS = "CONTAINS"
ALIAS = "ALIAS"
FUZZY = "FUZZY"
NO_MATCH = "NO_MATCH"

MATCH_SCORES = {
    EXACT: 500,         # 绝对优先(搜名字找本人) — 2026-08-14 回归: 300万粉 PREFIX 也不得反超 EXACT
    NORMALIZED: 480,
    PREFIX: 350,
    CONTAINS: 250,
    ALIAS: 220,
    FUZZY: 150,         # 上限; 具体按相似度 0-150
    NO_MATCH: 0,
}


def normalize_query(kw: str) -> str:
    """查询词规范化: NFKC(数学斜体/全角→半角) + 去空白 + 小写。

    2026-08-14 修复: "𝑿.四五六🍉" 的 𝑿(U+1D4BF 数学斜体) 不 NFKC 就匹配不上
    普通 "X.四五六" → FUZZY 66 被阈值丢弃 → 搜索结果 EMPTY。
    注意顺序: NFKC 必须先于 lower(NFKC(𝑿)=大写X, 之后再 lower 才是 x)。
    """
    import unicodedata

    if not kw:
        return ""
    s = unicodedata.normalize("NFKC", kw.strip())
    s = s.lower()
    # 全角→半角(兜底)
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return s.replace(" ", "")


def identity_confidence(nickname: str, query: str) -> dict:
    """身份确认: 返回 {match_type, match_score}。

    规则(用户 P0-11):
      nickname == query        → EXACT  (500)
      normalized 完全匹配       → NORMALIZED (480)
      昵称以 query 开头          → PREFIX (350)
      昵称包含 query            → CONTAINS (250)
      query 包含昵称(前缀/包含反向) → PREFIX/CONTAINS 降一档
      alias 匹配                → ALIAS  (220)
      其他(字符重叠度 > 50%)     → FUZZY  (0-150)
      无关联                     → NO_MATCH (丢弃)
    """
    if not nickname or not query:
        return {"match_type": NO_MATCH, "match_score": 0}

    raw_name = nickname.strip()
    q = normalize_query(query)
    n = normalize_query(raw_name)

    # 完全一致(带标点变体也算 EXACT 的近亲 NORMALIZED)
    if raw_name == query.strip():
        return {"match_type": EXACT, "match_score": MATCH_SCORES[EXACT]}
    if n == q:
        return {"match_type": NORMALIZED, "match_score": MATCH_SCORES[NORMALIZED]}

    # 前缀
    if n.startswith(q) and len(q) >= 2:
        return {"match_type": PREFIX, "match_score": MATCH_SCORES[PREFIX]}
    # 包含
    if q in n and len(q) >= 2:
        return {"match_type": CONTAINS, "match_score": MATCH_SCORES[CONTAINS]}
    # 反向: 查询包含昵称(如 query="阿哲哥哥的粉丝" name="阿哲")→ 降档
    if n in q and len(n) >= 2:
        return {"match_type": CONTAINS, "match_score": MATCH_SCORES[CONTAINS] - 30}

    # 模糊: 字符重叠率
    overlap = len(set(q) & set(n)) / max(len(set(q)), len(set(n)), 1)
    if overlap >= 0.7 and len(q) >= 2:
        score = int(150 * overlap)
        return {"match_type": FUZZY, "match_score": score}
    if overlap >= 0.5 and len(q) >= 3:
        score = int(100 * overlap)
        return {"match_type": FUZZY, "match_score": score}

    return {"match_type": NO_MATCH, "match_score": 0}


def relevance_filter(candidates: list[dict], query: str, min_match: str = CONTAINS) -> list[dict]:
    """候选发现 → 身份确认过滤。丢弃 NO_MATCH 和低于阈值的候选。

    用户要求: "宁可返回 0 个可信结果, 也不能返回一堆无关结果"。
    min_match: 最低保留档位(默认 CONTAINS; PREFIX/CONTAINS/FUZZY 可配置)
    """
    out = []
    for c in candidates:
        name = c.get("display_name") or ""
        conf = identity_confidence(name, query)
        if conf["match_type"] == NO_MATCH:
            continue
        # FUZZY 需要更高阈值才保留(用户: 模糊相似 0-150)
        if conf["match_type"] == FUZZY and conf["match_score"] < 100:
            continue
        c["match_type"] = conf["match_type"]
        c["match_score"] = conf["match_score"]
        out.append(c)
    return out


def deduplicate(candidates: list[dict]) -> list[dict]:
    """同一 platform + platform_user_id 去重。

    保留规则(优先级):
      1. match_score 更高
      2. 同分 → follower_count/fans 更高(平台实时数据 > local 静态占位)
    """
    seen: dict[tuple, dict] = {}
    for c in candidates:
        key = (c.get("platform"), c.get("user_id") or c.get("platform_user_id"))
        if key in seen:
            cur = seen[key]
            c_score = c.get("match_score", 0)
            cur_score = cur.get("match_score", 0)
            c_fans = c.get("follower_count") if c.get("follower_count") is not None else c.get("fans") or 0
            cur_fans = cur.get("follower_count") if cur.get("follower_count") is not None else cur.get("fans") or 0
            if c_score > cur_score or (c_score == cur_score and c_fans > cur_fans):
                seen[key] = c
        else:
            seen[key] = c
    return list(seen.values())


def _rank_items_legacy(items: list[dict], query: str) -> list[dict]:
    """Rank Model(2026-08-14 方案 B + 高粉升级):
      已订阅 +1000 > 匹配分(EXACT 350...FUZZY 150) > 粉丝权重(0-200, 对数放大)
      高粉升级: EXACT 为僵尸号(<1000粉)或不存在时, ≥10万粉 CONTAINS 按 PREFIX 档打分
               (平台搜索"四五六"时 105万粉主播必然排最前; 但 EXACT 是真实主播时绝对优先)
    """
    q = normalize_query(query)
    # 2026-08-14: EXACT 候选全部是僵尸号(粉丝 < 1000) 或不存在 → 允许高粉 CONTAINS 升级
    exact_cands = [it for it in items if it.get("match_type") == EXACT]
    exact_is_zombie = bool(exact_cands) and all(
        (it.get("follower_count") or it.get("fans") or 0) < 1000 for it in exact_cands
    )
    allow_upgrade = (not exact_cands) or exact_is_zombie
    for it in items:
        name = it.get("display_name") or ""
        # 匹配分
        score = it.get("match_score", 0)
        fans = it.get("follower_count") or it.get("fans") or 0
        # 2026-08-14 高粉强相关升级: CONTAINS 且 ≥10万粉, 且 EXACT 未"占位" → 按 PREFIX 档
        #   背景: 名字带前缀(如 "x.四五六🍉")NFKC 后 query 不在开头 → 只能 CONTAINS,
        #   但平台搜索 "四五六" 时 105万粉主播必然排最前(用户意图 = 高粉+名字相关)。
        if allow_upgrade and it.get("match_type") == CONTAINS and fans >= 100000:
            score = max(score, MATCH_SCORES[PREFIX])
            it["match_type"] = PREFIX
            it["match_score"] = MATCH_SCORES[PREFIX]
        # 订阅 boost
        if it.get("is_subscribed"):
            score += SUBSCRIPTION_BOOST
        # 粉丝权重(0-FANS_MAX_BOOST, 对数放大让百万粉主播能反超低粉 EXACT)
        # 公式: log10(fans+1) × FANS_SCALE, FANS_MAX_BOOST 兜底
        # 105万粉丝: log10(1.05e6) × 30 ≈ 180 (可反超 EXACT)
        # 1万: log10(1e4) × 30 = 120
        # 1000: log10(1e3) × 30 ≈ 90
        # 100: log10(101) × 30 ≈ 60
        # 10: log10(11) × 30 ≈ 31
        # 1: log10(2) × 30 ≈ 9
        # 2026-08-14: 僵尸号 EXACT(粉丝 < 1000) 不享受粉丝权重
        #   — 否则 111 粉 EXACT(500+61) 会压过 105万粉升级(350+180), 违背"搜名字找大主播"意图
        if fans > 0 and not (it.get("match_type") == EXACT and fans < 1000):
            import math
            fans_boost = int(min(FANS_MAX_BOOST, math.log10(fans + 1) * FANS_SCALE))
            score += fans_boost
        it["_rank_score"] = score

    # 排序: 分数降序; 同分按粉丝降序
    items.sort(key=lambda x: (x.get("_rank_score", 0), x.get("follower_count") or x.get("fans") or 0), reverse=True)
    for it in items:
        it.pop("_rank_score", None)
    return items


def rank_items(items: list[dict], query: str) -> list[dict]:
    """按订阅、匹配、实时直播状态、粉丝数分层排序。

    ``is_live`` 是搜索供应商的即时值；已入库账号则可由 ``live_state``
    补充。只有任一字段明确为直播，才获得同级的直播优先级。
    """
    def sort_key(it: dict) -> tuple:
        fans = it.get("follower_count") or it.get("fans") or 0
        is_live = bool(it.get("is_live")) or it.get("live_state") == "LIVE"
        return (
            -int(bool(it.get("is_subscribed"))),
            -int(it.get("match_score", 0)),
            -int(is_live),
            -int(fans),
            normalize_query(it.get("display_name") or ""),
            str(it.get("platform") or ""),
            str(it.get("user_id") or it.get("platform_user_id") or ""),
        )

    items.sort(key=sort_key)
    return items


def to_dto(items: list[dict]) -> list[dict]:
    """统一 SearchResult DTO 字段(前端不再猜)。"""
    out = []
    for it in items:
        out.append({
            "anchor_id": it.get("anchor_id"),
            "platform": it.get("platform"),
            "platform_user_id": it.get("user_id") or it.get("platform_user_id"),
            "display_name": it.get("display_name", ""),
            "avatar": it.get("avatar"),
            "follower_count": it.get("follower_count") if it.get("follower_count") is not None else it.get("fans"),
            "is_subscribed": bool(it.get("is_subscribed")),
            "subscription_id": it.get("subscription_id"),
            "match_type": it.get("match_type", NO_MATCH),
            "match_score": it.get("match_score", 0),
            "live_state": it.get("live_state", "UNKNOWN"),
            "last_probe_at": it.get("last_probe_at"),
            "source": it.get("source", ""),
            "canonical_url": it.get("canonical_url", ""),
        })
    return out
