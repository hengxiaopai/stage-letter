"""主播路由: URL 解析 / 搜索 / 主播详情。

契约见 API-SPEC.md §4。
- POST /api/v1/anchors/parse: 粘 URL → 解析主播(用 adapter.parse_url + 探测)
- GET  /api/v1/anchors/search?platform=&keyword=: 按名字搜索主播(平台能力矩阵见 services/search.py)
- GET /api/v1/anchors/{anchor_id}: 主播详情(含实时状态 + 当前 session + 最近 sessions)
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.search import (
    SearchResult,
    SearchUnsupportedError,
    parse_anchor_url,
    search_all_platforms,
    search_anchors,
)
from api.services.search_browser import Status as SearchStatus
from core.db import get_db
from core.live_state import from_platform_account
from core.models import Anchor, LiveSession, PlatformAccount, User, UserSubscription
from stage_letter.infrastructure.db.models import (
    CreatorModel,
    CreatorProfileModel,
    FollowModel,
    LiveSessionModel,
    NotificationPreferenceModel,
    PlatformAccountModel,
)

router = APIRouter()


class SearchResultItem(BaseModel):
    platform: str
    user_id: str
    display_name: str
    avatar: str | None = None
    fans: int = 0
    canonical_url: str
    is_live: bool = False
    is_existing: bool = False
    anchor_id: int | None = None
    subscription_id: int | None = None  # 当前用户对该主播的订阅 id(用于取消)
    confidence: str | None = None        # HIGH / LOW (Layer 0 来源)
    followers_unknown: bool = False      # True 表示 fans=0 是未知, 不是真的 0


class SearchResponseV2(BaseModel):
    """V2 结构化搜索响应 (P0-09)。"""
    status: str                  # SUCCESS / EMPTY / DEGRADED / TIMEOUT / BLOCKED / PARSE_ERROR
    items: list[SearchResultItem]
    ms_used: int = 0
    source: str = ""             # 哪条路径: local_index / bilibili_api / huya_dom / douyu_dom / login_required / user_page
    hint: str = ""               # 给前端的友好提示
    platform: str = ""
    keyword: str = ""


# ── P0-10/P0-11: Search Core V3 DTO ──

class SearchResultDTO(BaseModel):
    """统一搜索结果(前端不再猜: 相关性/订阅/粉丝都由后端决定)。"""
    anchor_id: int | None = None
    platform: str
    platform_user_id: str
    display_name: str
    avatar: str | None = None
    follower_count: int | None = None
    is_subscribed: bool = False
    subscription_id: int | None = None
    match_type: str = "NO_MATCH"     # EXACT/PREFIX/CONTAINS/ALIAS/FUZZY/NORMALIZED
    match_score: int = 0
    live_state: str = "UNKNOWN"      # LIVE/OFFLINE/CONFIRMING/UNKNOWN
    last_probe_at: str | None = None
    source: str = ""                 # local_index / bilibili_api / huya_dom / douyu_dom ...
    canonical_url: str = ""


class SearchV3Response(BaseModel):
    """Search Core V3 聚合响应(P0-10/11)。"""
    status: str                      # SUCCESS / PARTIAL / BLOCKED
    items: list[SearchResultDTO] = []
    platform_status: dict | None = None  # {platform: {status, hint, count}}
    ms_used: int = 0
    hint: str = ""
    platform: str = ""
    keyword: str = ""


class ParseRequest(BaseModel):
    url: str


class ParseResponse(BaseModel):
    platform: str
    platform_user_id: str
    room_id: str | None = None
    display_name: str | None = None
    avatar: str | None = None
    canonical_url: str
    is_existing: bool = False
    anchor_id: int | None = None


class SessionInfo(BaseModel):
    id: int
    title: str | None = None
    cover: str | None = None
    started_at: str | None = None   # 友好时间: 08-13 12:09
    ended_at: str | None = None
    started_at_iso: str | None = None  # 原始 ISO(UTC),供前端算时长
    ended_at_iso: str | None = None
    viewer_count: int | None = None
    # 2026-08-14: 开播时间来源 platform=真实 / probe=探测时刻兜底(前端不显示精确时间)
    started_at_source: str = "probe"


class SessionHistoryItem(BaseModel):
    session_id: str
    account_id: str
    platform: str
    title: str | None = None
    cover: str | None = None
    viewer_count: int | None = None
    provider_room_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    state: str
    started_at_source: str
    duration_seconds: int | None = None
    duration_basis: str


class SessionHistoryResponse(BaseModel):
    items: list[SessionHistoryItem]
    next_cursor: str | None = None


def _fmt_time(dt: datetime | None) -> str | None:
    """UTC → 北京时间友好格式 (MM-DD HH:mm)。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(timezone(timedelta(hours=8)))
    return local.strftime("%m-%d %H:%M")


def _fmt_iso(dt: datetime | None) -> str | None:
    """datetime → ISO 字符串(UTC),供前端计算时长等。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class PlatformStatus(BaseModel):
    platform_account_id: int
    platform: str
    platform_user_id: str
    canonical_url: str
    is_live: bool | None = None   # P0-L3: None = 状态确认中/未知
    last_status: str
    last_checked_at: datetime | None = None
    # P0-L3: 状态真相链统一字段
    live_state: str = "UNKNOWN"
    freshness: str = "stale"
    last_probe_at: str | None = None
    current_session: SessionInfo | None = None
    is_following: bool = False
    reminder_enabled: bool | None = None


class AnchorDetail(BaseModel):
    id: int
    display_name: str
    avatar: str | None = None
    bio: str | None = None
    platforms: list[PlatformStatus] = []
    recent_sessions: list[SessionInfo] = []


async def _viewer_context_by_account(
    db: AsyncSession,
    *,
    openid: str | None,
    account_ids: list[int],
) -> dict[int, dict[str, bool | None]]:
    """Return the authenticated viewer's formal follow/reminder facts."""
    if not openid or not account_ids:
        return {}

    user = await db.scalar(select(User).where(User.openid == openid))
    if user is None:
        return {}

    follows = (
        await db.execute(
            select(FollowModel).where(
                FollowModel.user_id == user.id,
                FollowModel.platform_account_id.in_(account_ids),
            )
        )
    ).scalars().all()
    preferences = (
        await db.execute(
            select(NotificationPreferenceModel).where(
                NotificationPreferenceModel.user_id == user.id,
                NotificationPreferenceModel.platform_account_id.in_(account_ids),
            )
        )
    ).scalars().all()

    followed_ids = {follow.platform_account_id for follow in follows}
    enabled_by_id = {
        preference.platform_account_id: preference.enabled
        for preference in preferences
    }
    return {
        account_id: {
            "is_following": account_id in followed_ids,
            "reminder_enabled": enabled_by_id.get(account_id),
        }
        for account_id in account_ids
    }


def _parse_url(url: str) -> dict:
    """用平台 adapter 解析 URL,返回 {platform, platform_user_id, room_id, canonical_url}。

    V1 简化: 从 URL 形态判断平台,提取 room_id/uid。
    完整实现可接 adapter.parse_url(Gate 4 联调时完善)。
    """
    url = url.strip()
    # B站: 支持 直播间 / 主页(space)/ 普通页
    if "bilibili.com" in url:
        import re
        # 主页: space.bilibili.com/{mid}
        m = re.match(r"^https?://(?:www\.)?space\.bilibili\.com/(\d+)", url)
        if m:
            mid = m.group(1)
            return {
                "platform": "bilibili",
                "platform_user_id": mid,
                "room_id": mid,
                "canonical_url": f"https://space.bilibili.com/{mid}",
            }
        m = re.search(r"/(\d+)", url)
        if m:
            rid = m.group(1)
            return {
                "platform": "bilibili",
                "platform_user_id": rid,
                "room_id": rid,
                "canonical_url": f"https://live.bilibili.com/{rid}",
            }
        raise HTTPException(status_code=400, detail="B站链接解析失败")
    # 虎牙
    if "huya.com" in url:
        import re
        m = re.search(r"huya\.com/(\w+)", url)
        if m:
            rid = m.group(1)
            return {
                "platform": "huya",
                "platform_user_id": rid,
                "room_id": rid,
                "canonical_url": f"https://www.huya.com/{rid}",
            }
        raise HTTPException(status_code=400, detail="虎牙链接解析失败")
    # 斗鱼
    if "douyu.com" in url:
        import re
        m = re.search(r"douyu\.com/(\d+)", url)
        if m:
            rid = m.group(1)
            return {
                "platform": "douyu",
                "platform_user_id": rid,
                "room_id": rid,
                "canonical_url": f"https://www.douyu.com/{rid}",
            }
        raise HTTPException(status_code=400, detail="斗鱼链接解析失败")
    # 抖音: 支持 直播间 / 用户主页(douyin.com/user/{sec_uid})
    if "douyin.com" in url:
        import re
        m = re.search(r"douyin\.com/user/([A-Za-z0-9_\-]+)", url)
        if m:
            sec_uid = m.group(1)
            return {
                "platform": "douyin",
                "platform_user_id": sec_uid,
                "room_id": None,
                "canonical_url": f"https://www.douyin.com/user/{sec_uid}",
            }
        m = re.search(r"/(\d{10,25})", url)
        if m:
            rid = m.group(1)
            return {
                "platform": "douyin",
                "platform_user_id": rid,
                "room_id": rid,
                "canonical_url": f"https://live.douyin.com/{rid}",
            }
        raise HTTPException(status_code=400, detail="抖音链接解析失败(需 live 房间号或 user 主页链接)")
    raise HTTPException(status_code=400, detail="不支持的链接格式")


@router.get("/anchors/_search", response_model=SearchV3Response)
async def search(
    platform: str = Query(..., description="all / bilibili / huya / douyu / douyin"),
    keyword: str = Query(..., min_length=1, max_length=50),
    limit: int = Query(15, ge=1, le=30),
    openid: str | None = Query(None, description="当前用户 openid(查订阅状态)"),
    db: AsyncSession = Depends(get_db),
) -> SearchV3Response:
    """P0-10/P0-11 Search Core V3 搜索。

    - platform=all → 真正并发搜索所有可搜索平台(不再依赖用户点过哪些 Tab)
    - 单平台 → 走同一管道(过滤/去重/订阅/融合/排名), 结果一致
    - 返回统一 SearchResult[] DTO(前端只展示, 不自己 merge/排序)

    P0-09: 抖音 BLOCKED 标注在 platform_status, 不阻塞其他平台。
    """
    try:
        # 当前用户 id(订阅标注用)
        user_id = None
        if openid:
            r = await db.execute(select(User).where(User.openid == openid))
            u = r.scalar_one_or_none()
            if u is not None:
                user_id = u.id

        target_platforms = None if platform == "all" else [platform]
        agg = await search_all_platforms(
            db=db,
            keyword=keyword,
            user_id=user_id,
            limit=limit,
            timeout_s=8,
            platforms=target_platforms,
        )
    except SearchUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))

    return SearchV3Response(
        status=agg["status"],
        items=agg["items"],
        platform_status=agg.get("platform_status"),
        ms_used=agg["ms_used"],
        hint="",
        platform=platform,
        keyword=keyword,
    )


@router.post("/anchors/parse", response_model=ParseResponse)
async def parse_anchor(
    req: ParseRequest, db: AsyncSession = Depends(get_db)
) -> ParseResponse:
    """粘贴 URL → 解析主播基本信息(含真实主播名,调平台 adapter 探测)。"""
    parsed = _parse_url(req.url)
    platform = parsed["platform"]

    # 调 adapter 拿主播名/头像/实时状态(同步代码,放线程池)
    display_name = None
    avatar = None
    is_live = None
    try:
        import asyncio

        def _probe():
            # ── 主页 URL 专用分支(未开播也能解析名字)──
            if platform == "bilibili" and "space.bilibili.com" in parsed["canonical_url"]:
                # B站主页: 用户信息接口(免签名 card 接口,返回名字/头像)
                try:
                    import httpx
                    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
                    mid = parsed["platform_user_id"]
                    r = httpx.get(
                        f"https://api.bilibili.com/x/web-interface/card?mid={mid}",
                        headers={"User-Agent": UA, "Referer": f"https://space.bilibili.com/{mid}"},
                        timeout=10,
                    )
                    d = r.json()
                    if d.get("code") == 0:
                        info = d.get("data", {}).get("card", {})
                        return {
                            "uname": info.get("name"),
                            "avatar": info.get("face"),
                            "state": "OFFLINE",  # 主页订阅: 默认未开播,探测后更新
                        }
                except Exception:
                    pass
                return {}
            if platform == "douyin" and parsed["canonical_url"].startswith("https://www.douyin.com/user/"):
                # 抖音主页: 用 Playwright 打开 user page 提取昵称/头像(无需登录, P0-09)
                try:
                    from api.services.search_browser import parse_douyin_user_page

                    r = parse_douyin_user_page(parsed["canonical_url"], timeout_s=8)
                    if r.status == "SUCCESS" and r.items:
                        it = r.items[0]
                        return {
                            "uname": it["display_name"],
                            "avatar": it["avatar"],
                            "state": "UNKNOWN",
                        }
                except Exception:
                    pass
                # 兜底: 解析失败只返回 sec_uid 占位
                return {"state": "UNKNOWN"}
            if platform == "douyin":
                from platform_adapters.douyin.adapter import DouyinAdapter
                return DouyinAdapter().get_status(parsed["canonical_url"])
            if platform == "bilibili":
                from platform_adapters.bilibili.adapter import BilibiliAdapter
                result = BilibiliAdapter().get_status(parsed["canonical_url"])
                # B站 adapter 不返回主播名,补抓房间页 uname
                try:
                    import httpx, re
                    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
                    html = httpx.get(parsed["canonical_url"], headers={"User-Agent": UA, "Referer": "https://live.bilibili.com/"}, timeout=8).text
                    names = re.findall(r'"uname"\s*:\s*"([^"]+)"', html)
                    if names:
                        result["uname"] = names[0]
                except Exception:
                    pass
                return result
            if platform == "huya":
                from platform_adapters.huya.adapter import HuyaAdapter
                result = HuyaAdapter().get_status(parsed["canonical_url"])
                # 虎牙 adapter 不返回主播名,补抓房间页 nick
                try:
                    import httpx, re
                    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
                    html = httpx.get(parsed["canonical_url"], headers={"User-Agent": UA, "Referer": "https://www.huya.com/"}, timeout=8).text
                    names = re.findall(r'"nick"\s*:\s*"([^"]+)"', html)
                    if names:
                        result["nickname"] = names[0]
                except Exception:
                    pass
                return result
            if platform == "douyu":
                from platform_adapters.douyu.adapter import DouyuAdapter
                result = DouyuAdapter().get_status(parsed["canonical_url"])
                try:
                    import httpx, re
                    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
                    html = httpx.get(parsed["canonical_url"], headers={"User-Agent": UA, "Referer": "https://www.douyu.com/"}, timeout=8).text
                    m = re.findall(r'"nickname"\s*:\s*"([^"]+)"', html)
                    if m:
                        result["nickname"] = m[0]
                    else:
                        # 斗鱼名字异步加载,用 title 提取: "房间名_主播名直播_主播名斗鱼直播"
                        t = re.search(r"<title>([^<]+)</title>", html)
                        if t:
                            parts = re.split(r"_", t.group(1))
                            name = parts[1] if len(parts) > 1 else parts[0]
                            name = name.replace("直播", "").strip()
                            if name:
                                result["nickname"] = name
                except Exception:
                    pass
                return result
            return {}

        result = await asyncio.to_thread(_probe)
        display_name = result.get("nickname") or result.get("uname") or result.get("name")
        avatar = result.get("avatar")
        state = result.get("state")
        is_live = state == "ONLINE"
        # 抖音: platform_user_id 用真实的 web_rid/room_id(adapter 归一化后)
        if platform == "douyin":
            real_rid = result.get("web_rid") or result.get("room_id")
            if real_rid and str(real_rid).isdigit():
                parsed["platform_user_id"] = str(real_rid)
                parsed["room_id"] = str(real_rid)
                parsed["canonical_url"] = f"https://live.douyin.com/{real_rid}"
    except Exception as e:
        # 探测失败不阻塞解析,名称留空
        import logging
        logging.getLogger("stageletter.api").warning("parse 探测失败 %s: %s", platform, e)

    # 查是否已存在(用归一化后的 platform_user_id)
    r = await db.execute(
        select(PlatformAccount, Anchor)
        .join(Anchor, PlatformAccount.anchor_id == Anchor.id)
        .where(
            PlatformAccount.platform == platform,
            PlatformAccount.platform_user_id == parsed["platform_user_id"],
        )
    )
    row = r.first()
    is_existing = row is not None

    return ParseResponse(
        platform=platform,
        platform_user_id=parsed["platform_user_id"],
        room_id=parsed.get("room_id"),
        display_name=display_name,
        avatar=avatar,
        canonical_url=parsed["canonical_url"],
        is_existing=is_existing,
        anchor_id=row[1].id if row else None,
    )


@router.get("/anchors/{anchor_id}/sessions", response_model=SessionHistoryResponse)
async def anchor_session_history(
    request: Request,
    anchor_id: int,
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
) -> SessionHistoryResponse:
    try:
        page = await request.app.state.stage_letter_services.session_insights.history(
            str(anchor_id), limit=limit, cursor=cursor
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionHistoryResponse(
        items=[
            SessionHistoryItem(
                session_id=row.session_id, account_id=row.account_id,
                platform=row.platform, title=row.title, cover=row.cover,
                viewer_count=row.viewer_count, provider_room_id=row.provider_room_id,
                started_at=row.display_started_at, ended_at=row.closed_at,
                state="LIVE" if row.closed_at is None else "ENDED",
                started_at_source=row.started_at_source,
                duration_seconds=row.duration_seconds,
                duration_basis="IN_PROGRESS" if row.closed_at is None else "PROBE_BOUNDED",
            ) for row in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/anchors/{anchor_id}/calendar")
async def anchor_session_calendar(
    request: Request,
    anchor_id: int,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
) -> dict:
    try:
        result = await request.app.state.stage_letter_services.session_insights.calendar(str(anchor_id), month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["coverage"] = asdict(result["coverage"])
    return result


@router.get("/anchors/{anchor_id}/stats")
async def anchor_session_statistics(
    request: Request,
    anchor_id: int,
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
) -> dict:
    try:
        result = await request.app.state.stage_letter_services.session_insights.statistics(
            str(anchor_id), date_from, date_to
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["coverage"] = asdict(result["coverage"])
    return result


@router.get("/anchors/{anchor_id}", response_model=AnchorDetail)
async def get_anchor(
    anchor_id: int,
    openid: str | None = Query(None, description="current viewer openid"),
    db: AsyncSession = Depends(get_db),
) -> AnchorDetail:
    anchor = await db.get(Anchor, anchor_id)
    if anchor is None:
        return await _get_formal_creator_detail(anchor_id, db, openid=openid)

    # 平台账号 + 实时状态
    pas = (
        await db.execute(
            select(PlatformAccount).where(PlatformAccount.anchor_id == anchor_id)
        )
    ).scalars().all()

    viewer_by_account = await _viewer_context_by_account(
        db,
        openid=openid,
        account_ids=[pa.id for pa in pas],
    )

    platforms = []
    for pa in pas:
        # 当前 OPEN session
        sess_r = await db.execute(
            select(LiveSession)
            .where(
                LiveSession.platform_account_id == pa.id,
                LiveSession.state == "OPEN",
            )
            .order_by(LiveSession.started_at.desc())
            .limit(1)
        )
        cur = sess_r.scalar_one_or_none()
        # P0-L3: 统一 Current Live State
        ls = from_platform_account(pa)
        viewer = viewer_by_account.get(pa.id, {})
        platforms.append(
            PlatformStatus(
                platform_account_id=pa.id,
                platform=pa.platform,
                platform_user_id=pa.platform_user_id,
                canonical_url=pa.canonical_url,
                is_live=ls["is_live"],
                last_status=pa.last_status,
                last_checked_at=pa.last_checked_at,
                live_state=ls["state"],
                freshness=ls["freshness"],
                last_probe_at=ls["last_probe_at"],
                is_following=bool(viewer.get("is_following", False)),
                reminder_enabled=viewer.get("reminder_enabled"),
                current_session=SessionInfo(
                    id=cur.id,
                    title=cur.title,
                    cover=cur.cover,
                    started_at=_fmt_time(cur.source_started_at or cur.started_at),
                    started_at_iso=_fmt_iso(cur.source_started_at or cur.started_at),
                    viewer_count=cur.viewer_count,
                    started_at_source=cur.started_at_source or "probe",
                ) if cur else None,
            )
        )

    # 最近 sessions
    recent = (
        await db.execute(
            select(LiveSession)
            .where(LiveSession.anchor_id == anchor_id)
            .order_by(LiveSession.started_at.desc())
            .limit(10)
        )
    ).scalars().all()

    return AnchorDetail(
        id=anchor.id,
        display_name=anchor.display_name,
        avatar=anchor.avatar,
        bio=anchor.bio,
        platforms=platforms,
        recent_sessions=[
            SessionInfo(
                id=s.id,
                title=s.title,
                cover=s.cover,
                started_at=_fmt_time(s.source_started_at or s.started_at),
                ended_at=_fmt_time(s.ended_at) or ("进行中" if s.ended_at is None else None),
                started_at_iso=_fmt_iso(s.source_started_at or s.started_at),
                ended_at_iso=_fmt_iso(s.ended_at),
                viewer_count=s.viewer_count,
                started_at_source=s.started_at_source or "probe",
            )
            for s in recent
        ],
    )


async def _get_formal_creator_detail(
    creator_id: int,
    db: AsyncSession,
    *,
    openid: str | None = None,
) -> AnchorDetail:
    """Read a canonical Creator when no legacy Anchor mirror exists."""

    creator = await db.get(CreatorModel, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="主播不存在")
    profile = await db.scalar(
        select(CreatorProfileModel).where(
            CreatorProfileModel.creator_id == creator_id
        )
    )
    accounts = (
        await db.execute(
            select(PlatformAccountModel).where(
                PlatformAccountModel.creator_id == creator_id
            )
        )
    ).scalars().all()

    viewer_by_account = await _viewer_context_by_account(
        db,
        openid=openid,
        account_ids=[account.id for account in accounts],
    )

    platforms: list[PlatformStatus] = []
    for account in accounts:
        viewer = viewer_by_account.get(account.id, {})
        current = await db.scalar(
            select(LiveSessionModel)
            .where(
                LiveSessionModel.platform_account_id == account.id,
                LiveSessionModel.closed_at.is_(None),
            )
            .order_by(LiveSessionModel.opened_at.desc())
            .limit(1)
        )
        platforms.append(
            PlatformStatus(
                platform_account_id=account.id,
                platform=account.platform,
                platform_user_id=account.platform_user_id,
                canonical_url=account.canonical_url or "",
                is_live=True if current is not None else None,
                last_status="LIVE" if current is not None else "UNKNOWN",
                live_state="LIVE" if current is not None else "UNKNOWN",
                freshness="fresh" if current is not None else "never",
                is_following=bool(viewer.get("is_following", False)),
                reminder_enabled=viewer.get("reminder_enabled"),
                current_session=(
                    SessionInfo(
                        id=current.id,
                        title=current.title,
                        cover=current.cover,
                        started_at=_fmt_time(current.source_started_at or current.opened_at),
                        started_at_iso=_fmt_iso(current.source_started_at or current.opened_at),
                        viewer_count=current.viewer_count,
                        started_at_source=current.started_at_source or "probe",
                    )
                    if current is not None
                    else None
                ),
            )
        )

    recent = (
        await db.execute(
            select(LiveSessionModel)
            .join(
                PlatformAccountModel,
                LiveSessionModel.platform_account_id == PlatformAccountModel.id,
            )
            .where(PlatformAccountModel.creator_id == creator_id)
            .order_by(LiveSessionModel.opened_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return AnchorDetail(
        id=creator_id,
        display_name=(
            profile.display_name
            if profile is not None and profile.display_name
            else "未知主播"
        ),
        avatar=None if profile is None else profile.avatar_url,
        bio=None if profile is None else profile.bio,
        platforms=platforms,
        recent_sessions=[
            SessionInfo(
                id=session.id,
                title=session.title,
                cover=session.cover,
                started_at=_fmt_time(session.source_started_at or session.opened_at),
                ended_at=_fmt_time(session.closed_at)
                or ("进行中" if session.closed_at is None else None),
                started_at_iso=_fmt_iso(session.source_started_at or session.opened_at),
                ended_at_iso=_fmt_iso(session.closed_at),
                viewer_count=session.viewer_count,
                started_at_source=session.started_at_source or "probe",
            )
            for session in recent
        ],
    )
