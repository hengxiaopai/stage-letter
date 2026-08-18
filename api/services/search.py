"""主播搜索服务: 按平台 + 关键字搜索主播。

V2 (2026-08-13) 改造:
- 结构化返回 SearchResult {status, items, hint, ms_used, source}
- Layer 0 本地索引: anchors.display_name ILIKE 命中, 0 延迟
- Layer 1 主路径: B站 API / 虎牙斗鱼 DOM / 抖音 BLOCKED (登录态必需)
- 8s 全局硬超时 (configurable)
- 抖音解析新路径: parse_douyin_url(url) 走粘贴链接
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.search_browser import (
    SearchResult,
    Status,
    parse_douyin_user_page,
    search_douyin_logged_in,
    search_douyu,
    search_huya,
)
from core.models import Anchor, PlatformAccount

logger = logging.getLogger("stageletter.search")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"

DEFAULT_TIMEOUT_S = 8

# B站 5 分钟内存缓存(防风控)
_SEARCH_CACHE: dict[str, tuple[float, SearchResult]] = {}
_CACHE_TTL = 300


class SearchUnsupportedError(Exception):
    """该平台暂不支持搜索。"""


# ─────────────────────────────────────────────────────────────────────
# Layer 0: 本地索引 (anchors 表 display_name ILIKE)
# ─────────────────────────────────────────────────────────────────────

async def _layer0_local_index(
    db: AsyncSession, platform: str, keyword: str, limit: int = 10
) -> SearchResult:
    """从已订阅主播库找候选 — 0 延迟。

    命中策略:
      - exact: display_name == kw  → 高置信度
      - contains: display_name ILIKE %kw% → 低置信度 (但仍是已知锚点)
    """
    t0 = time.perf_counter()
    try:
        # ILIKE 不索引, 但 anchors 表小(<1万), 毫秒级
        # platform == "__all__" 表示不过滤平台(P0-10 全平台聚合用)
        stmt = (
            select(Anchor, PlatformAccount)
            .join(PlatformAccount, PlatformAccount.anchor_id == Anchor.id)
            .where(
                (Anchor.display_name == keyword)
                | Anchor.display_name.ilike(f"%{keyword}%")
            )
            .limit(limit)
        )
        if platform != "__all__":
            stmt = stmt.where(PlatformAccount.platform == platform)
        result = await db.execute(stmt)
        rows = result.all()

        items = []
        for anchor, pa in rows:
            # 置信度: exact match 优先
            confidence = "HIGH" if anchor.display_name == keyword else "LOW"
            items.append({
                "platform": pa.platform,
                "user_id": pa.platform_user_id,
                "display_name": anchor.display_name,
                "avatar": anchor.avatar,
                "fans": 0,  # Layer 0 不取 fans
                "canonical_url": pa.canonical_url,
                "is_live": False,  # 不假装知道实时状态
                "is_existing": True,
                "anchor_id": anchor.id,
                "platform_account_id": pa.id,
                "confidence": confidence,
            })
        ms = int((time.perf_counter() - t0) * 1000)
        if items:
            # 按置信度排序
            items.sort(key=lambda x: (x["confidence"] != "HIGH", len(x["display_name"])))
            return SearchResult(
                status=Status.SUCCESS,
                items=items[:limit],
                ms_used=ms,
                source="local_index",
                hint="本地索引命中",
                platform=platform,
                keyword=keyword,
            )
        return SearchResult(
            status=Status.EMPTY,
            items=[],
            ms_used=ms,
            source="local_index",
            hint="本地无该主播",
            platform=platform,
            keyword=keyword,
        )
    except Exception as e:
        logger.warning(f"Layer 0 失败: {e}")
        ms = int((time.perf_counter() - t0) * 1000)
        return SearchResult(
            status=Status.EMPTY,
            items=[],
            ms_used=ms,
            source="local_index_error",
            hint="本地索引异常",
            platform=platform,
            keyword=keyword,
        )


# ─────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────

async def search_anchors(
    platform: str,
    keyword: str,
    limit: int = 10,
    db: AsyncSession | None = None,
    use_local_index: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> SearchResult:
    """按平台搜索主播 (V2: 结构化返回)。

    Pipeline:
      0. Layer 0 本地索引 (可选, 0 延迟)
      1. B站 API / 浏览器搜索 (抖音 → BLOCKED)
    """
    platform = platform.lower()
    cache_key = f"{platform}:{keyword}"

    # 缓存 (仅缓存 SUCCESS/EMPTY, BLOCKED 不缓存)
    now = time.time()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL and cached[1].status in (Status.SUCCESS, Status.EMPTY):
        return cached[1]

    # Layer 0: 本地索引
    if use_local_index and db is not None:
        l0 = await _layer0_local_index(db, platform, keyword, limit)
        if l0.status == Status.SUCCESS and l0.items:
            # 仅当有 HIGH 置信度精确命中时直接返回
            high = [x for x in l0.items if x.get("confidence") == "HIGH"]
            if high:
                return SearchResult(
                    status=Status.SUCCESS,
                    items=high[:limit],
                    ms_used=l0.ms_used,
                    source="local_index_exact",
                    hint="本地精确命中",
                    platform=platform,
                    keyword=keyword,
                )
            # 否则继续 Layer 1 (用户可能想要新主播), 但 local 候选会 merge 进去
            _pending_l0_candidates = l0.items
        else:
            _pending_l0_candidates = []
    else:
        _pending_l0_candidates = []

    # Layer 1: 主路径
    if platform == "bilibili":
        result = await _search_bilibili(keyword, limit, timeout_s)
    elif platform == "douyin":
        # P0-S1: 登录态搜索(管理员扫码后可用); 未登录 → AUTH_REQUIRED
        result = await asyncio.to_thread(search_douyin_logged_in, keyword, limit, 10)
        if result.status == Status.BLOCKED and result.source == "auth_required":
            result.hint = "抖音搜索需登录态: 请管理员运行 tools/douyin_login_cli.py login 扫码后重试"
    elif platform == "huya":
        # 虎牙交互式(主播tab)固有 ~8-10s: 放宽到 10s, 精确结果 > 速度
        result = await asyncio.to_thread(search_huya, keyword, limit, 10)
    elif platform == "douyu":
        result = await asyncio.to_thread(search_douyu, keyword, limit, timeout_s)
    else:
        raise SearchUnsupportedError(f"未知平台 {platform}")

    # 把 Layer 0 LOW 候选 merge 进结果尾部 (仅当 Layer 1 没拿到精确匹配时)
    if _pending_l0_candidates and result.status in (Status.SUCCESS, Status.EMPTY):
        existing_keys = {(x["platform"], x["user_id"]) for x in result.items}
        for cand in _pending_l0_candidates:
            if (cand["platform"], cand["user_id"]) not in existing_keys:
                result.items.append(cand)
        if result.status == Status.EMPTY and result.items:
            result.status = Status.SUCCESS
            result.hint = "本地索引补充候选"

    # 缓存
    if result.status in (Status.SUCCESS, Status.EMPTY):
        _SEARCH_CACHE[cache_key] = (now, result)
    return result


# ─────────────────────────────────────────────────────────────────────
# 粘贴链接路径
# ─────────────────────────────────────────────────────────────────────

async def parse_anchor_url(
    url: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> SearchResult:
    """粘贴 URL → 解析主播基本信息(走平台特定的 parser)。

    抖音: parse_douyin_user_page (Playwright, 无登录)
    其他: 走现有 _parse_url 逻辑(纯正则, 已在 router 里)
    """
    url = url.strip()
    if "douyin.com" in url:
        return await asyncio.to_thread(parse_douyin_user_page, url, timeout_s)
    # 其他平台: 让 router 层用正则解析, 这里返回 EMPTY (由 router 接管)
    return SearchResult(
        status=Status.EMPTY,
        items=[],
        ms_used=0,
        source="delegate_to_router",
        hint="非抖音链接,由 router 层处理",
        platform="unknown",
        keyword=url,
    )


# ─────────────────────────────────────────────────────────────────────
# B 站
# ─────────────────────────────────────────────────────────────────────

async def _search_bilibili(keyword: str, limit: int, timeout_s: float) -> SearchResult:
    t0 = time.perf_counter()
    url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {"search_type": "bili_user", "keyword": keyword, "page": 1}
    # 2026-08-13 实测: 缺 Accept/Accept-Language 会返回 412 风控页
    headers = {
        "User-Agent": UA,
        "Referer": "https://search.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://search.bilibili.com",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, params=params, headers=headers)
            data = r.json()
    except Exception as e:
        ms = int((time.perf_counter()-t0)*1000)
        logger.warning("B站搜索异常: %s", e)
        return SearchResult(
            status=Status.TIMEOUT,
            items=[],
            ms_used=ms,
            source="bilibili_api",
            hint=f"B站搜索超时: {str(e)[:30]}",
            platform="bilibili",
            keyword=keyword,
        )

    # 2026-08-13: B站对同 IP 连续调用偶发 -412(回归 6 连发时常见)
    # → 间隔 800ms 重试 1 次(真实用户单次搜索几乎不会触发)
    if data.get("code") in (-412, -404) and time.perf_counter() - t0 < timeout_s - 1.5:
        import asyncio as _asyncio

        await _asyncio.sleep(0.8)
        try:
            async with httpx.AsyncClient(timeout=max(2.0, timeout_s - (time.perf_counter() - t0) - 0.5)) as client:
                r2 = await client.get(url, params=params, headers=headers)
                data2 = r2.json()
            if data2.get("code") == 0:
                data = data2
            elif data2.get("code") not in (-412, -404):
                data = data2
        except Exception as e2:
            logger.warning("B站重试仍失败: %s", e2)

    if data.get("code") != 0:
        ms = int((time.perf_counter()-t0)*1000)
        logger.warning("B站搜索失败 code=%s msg=%s", data.get("code"), data.get("message"))
        return SearchResult(
            status=Status.BLOCKED,
            items=[],
            ms_used=ms,
            source="bilibili_api",
            hint=f"B站搜索被风控 (code={data.get('code')})",
            platform="bilibili",
            keyword=keyword,
        )

    out = []
    for u in data.get("data", {}).get("result", [])[:limit]:
        avatar = u.get("upic") or ""
        if avatar.startswith("//"):
            avatar = "https:" + avatar
        out.append({
            "platform": "bilibili",
            "user_id": str(u.get("mid", "")),
            "display_name": u.get("uname", ""),
            "avatar": avatar,
            "fans": u.get("fans", 0),
            "canonical_url": f"https://space.bilibili.com/{u.get('mid', '')}",
            "is_live": False,
        })

    ms = int((time.perf_counter()-t0)*1000)
    return SearchResult(
        status=Status.SUCCESS if out else Status.EMPTY,
        items=out,
        ms_used=ms,
        source="bilibili_api",
        hint="",
        platform="bilibili",
        keyword=keyword,
    )

# ─────────────────────────────────────────────────────────────────────
# P0-10/P0-11: Search Core V3 全平台聚合
# ─────────────────────────────────────────────────────────────────────

async def search_all_platforms(
    db: AsyncSession,
    keyword: str,
    user_id: int | None = None,
    limit: int = 10,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    platforms: list[str] | None = None,
) -> dict:
    """P0-10: 「全部」= 真正独立搜索所有可搜索平台(并发)。

    流程(Search Core V3):
      Query → [Local | Bilibili | Huya | Douyu | Douyin] 并发收集
            → relevance_filter(身份确认, 无关丢弃)
            → deduplicate(platform+user_id)
            → subscription enrichment(已订阅标注)
            → profile merge(null 不覆盖)
            → rank(订阅+EXACT 优先, 粉丝 tie-breaker)
            → SearchResult[] DTO

    Returns:
        {
            "status": SUCCESS / EMPTY / BLOCKED,
            "items": [SearchResultDTO],
            "platform_status": {platform: {status, hint, items}},
            "ms_used": int,
        }
    """
    import time as _time

    from api.services import search_core

    t0 = _time.perf_counter()
    # platforms=None → 全部可搜索平台(「全部」Tab); 指定 → 只搜该平台(走同一管道)
    all_platforms = ["bilibili", "huya", "douyu", "douyin"]
    PLATFORMS = platforms or all_platforms

    async def _collect(platform: str) -> dict:
        """单平台候选收集(独立 try, 不因单个失败阻塞整体)。"""
        try:
            if platform == "bilibili":
                r = await _search_bilibili(keyword, limit, timeout_s)
            elif platform == "huya":
                r = await asyncio.to_thread(search_huya, keyword, limit, 10)
            elif platform == "douyu":
                r = await asyncio.to_thread(search_douyu, keyword, limit, timeout_s)
            elif platform == "douyin":
                r = await asyncio.to_thread(search_douyin_logged_in, keyword, limit, 10)
            else:
                return {"platform": platform, "status": Status.PARSE_ERROR, "items": [], "hint": "unknown"}
            return {
                "platform": platform,
                "status": r.status,
                "items": r.items,
                "hint": r.hint,
            }
        except Exception as e:
            logger.warning("平台 %s 收集失败: %s", platform, e)
            return {"platform": platform, "status": Status.PARSE_ERROR, "items": [], "hint": str(e)[:50]}

    # 1. 并发收集所有平台(抖音 0ms BLOCKED, B站 <1s, 虎牙/斗鱼 ~8s)
    collected = await asyncio.gather(*[_collect(p) for p in PLATFORMS])

    # 2. Layer 0 本地索引(所有平台)
    local_items: list[dict] = []
    try:
        l0 = await _layer0_local_index(db, "__all__", keyword, limit)
        if l0.status == Status.SUCCESS:
            local_items = l0.items
    except Exception:
        pass

    # 3. Candidate Pool = 各平台结果 + 本地索引
    candidates: list[dict] = list(local_items)
    platform_status: dict[str, dict] = {}
    for c in collected:
        for it in c["items"]:
            it["source"] = it.get("source") or f"{c['platform']}_platform"
            candidates.append(it)
        platform_status[c["platform"]] = {
            "status": c["status"],
            "hint": c["hint"],
            "count": len(c["items"]),
        }

    # 4. 身份确认 + 相关性过滤(丢弃无关: 赛事/频道/超长标题)
    candidates = search_core.relevance_filter(candidates, keyword)

    # 5. 去重(platform + user_id)
    candidates = search_core.deduplicate(candidates)

    # 6. 订阅 enrich(已订阅标注 + anchor_id)
    sub_map: dict[tuple, dict] = {}
    if user_id is not None:
        from core.models import UserSubscription

        subs = (
            await db.execute(
                select(UserSubscription, PlatformAccount)
                .join(PlatformAccount, UserSubscription.platform_account_id == PlatformAccount.id)
                .where(UserSubscription.user_id == user_id)
            )
        ).all()
        for sub, pa in subs:
            sub_map[(pa.platform, pa.platform_user_id)] = {
                "is_subscribed": True,
                "subscription_id": sub.id,
                "anchor_id": pa.anchor_id,
            }

    for it in candidates:
        key = (it.get("platform"), it.get("user_id") or it.get("platform_user_id"))
        sub = sub_map.get(key)
        if sub:
            it["is_subscribed"] = True
            it["subscription_id"] = sub["subscription_id"]
            it["anchor_id"] = sub["anchor_id"]
        else:
            it["is_subscribed"] = False
            it["subscription_id"] = None

    # 7. Profile merge: remote follower_count 非空 → 沉淀到 anchor; null 不覆盖
    await _merge_profile(db, candidates)

    # 8. Rank
    ranked = search_core.rank_items(candidates, keyword)

    # 9. DTO
    items = search_core.to_dto(ranked)[:limit]

    ms = int((_time.perf_counter() - t0) * 1000)
    any_success = any(c["status"] == Status.SUCCESS for c in collected)
    any_items = bool(items)
    all_blocked = all(c["status"] in (Status.BLOCKED, Status.PARSE_ERROR) for c in collected)
    return {
        # 语义: 全 BLOCKED → BLOCKED; 有 SUCCESS 或拿到结果 → SUCCESS; 否则 EMPTY(平台全失败/超时但有提示)
        "status": (
            Status.BLOCKED if all_blocked else
            (Status.SUCCESS if (any_success or any_items) else Status.EMPTY)
        ),
        "items": items,
        "platform_status": platform_status,
        "ms_used": ms,
    }


async def _merge_profile(db: AsyncSession, items: list[dict]) -> None:
    """字段级融合(P0-11): remote follower_count 沉淀到 anchor profile; null 不覆盖。

    - remote 有 follower_count → 更新 anchor.follower_count + profile_last_verified_at
    - remote 无 → 保留 anchor 已有值(不覆盖, 不写 null)
    """
    from core.models import Anchor

    anchor_ids = {it.get("anchor_id") for it in items if it.get("anchor_id")}
    if not anchor_ids:
        return
    anchors = (await db.execute(select(Anchor).where(Anchor.id.in_(anchor_ids)))).scalars().all()
    anchor_map = {a.id: a for a in anchors}

    for it in items:
        a = anchor_map.get(it.get("anchor_id"))
        if a is None:
            continue
        remote_fans = it.get("follower_count")
        if remote_fans is None:
            remote_fans = it.get("fans")
        # null 不覆盖: remote 有真实粉丝数才更新
        if remote_fans is not None and remote_fans > 0:
            if a.follower_count != remote_fans:
                a.follower_count = remote_fans
                a.profile_last_verified_at = datetime.now(timezone.utc)
                it["follower_count"] = remote_fans
        else:
            # remote 无数据 → 用本地沉淀值(不显示 null)
            if a.follower_count:
                it["follower_count"] = a.follower_count
    try:
        await db.commit()
    except Exception as e:
        logger.warning("profile merge commit 失败: %s", e)
        await db.rollback()
