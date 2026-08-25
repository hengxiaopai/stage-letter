"""TikHub-backed Douyin creator lookup.

This is intentionally an optional transport.  A missing credential is an
explicit configuration state, never a reason to fall back to fragile browser
automation and report a misleading timeout to Mini Program users.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from core.config import settings
from api.services.search_browser import SearchResult, Status


# The non-V2 endpoint returns the App's user_info object, including sec_uid.
# V2 returns creator-monitor summaries and cannot establish a profile identity.
API_URL = "https://api.tikhub.io/api/v1/douyin/search/fetch_user_search"


def is_configured() -> bool:
    return bool(settings.tikhub_api_key)


def _token() -> str:
    return settings.tikhub_api_key


def _avatar(user: dict[str, Any]) -> str:
    for key in ("avatar_larger", "avatar_medium", "avatar_thumb"):
        value = user.get(key)
        if isinstance(value, dict):
            urls = value.get("url_list") or value.get("urlList") or []
            if urls and isinstance(urls[0], str):
                return urls[0]
    return ""


def _users(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle documented and minor envelope variations without guessing IDs."""
    data: Any = payload.get("data") or {}
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    # TikHub's outer billing envelope is ``data`` and its upstream payload is
    # nested once more at ``data.data``.  Retain the direct form too so a
    # provider envelope change does not silently turn valid users into EMPTY.
    nested = data.get("data") if isinstance(data.get("data"), dict) else data
    values = nested.get("user_list") or nested.get("userList") or []
    users: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("user_info"), dict):
            users.append(item)
            continue
        # The current App-search envelope stores the documented user_info JSON
        # inside dynamic_patch.raw_data rather than directly on each list row.
        raw = (item.get("dynamic_patch") or {}).get("raw_data")
        if not isinstance(raw, str):
            continue
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(decoded.get("user_info"), dict):
            users.append({"user_info": decoded["user_info"]})
    return users


def search_users(keyword: str, limit: int = 10, timeout_s: float = 8) -> SearchResult:
    """Search Douyin users by nickname and return canonical sec_uid identities."""
    started = time.perf_counter()
    if not is_configured():
        return SearchResult(
            status=Status.BLOCKED,
            items=[],
            hint="抖音昵称搜索尚未配置数据源；请粘贴主页链接，或配置 TIKHUB_API_KEY",
            source="tikhub_unconfigured",
            platform="douyin",
            keyword=keyword,
        )

    try:
        response = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {_token()}", "Accept": "application/json"},
            json={
                "keyword": keyword,
                "cursor": 0,
                "douyin_user_fans": "",
                "douyin_user_type": "",
                "search_id": "",
            },
            timeout=timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException:
        return SearchResult(
            status=Status.TIMEOUT,
            items=[],
            ms_used=int((time.perf_counter() - started) * 1000),
            hint="抖音昵称搜索数据源超时，请稍后重试",
            source="tikhub",
            platform="douyin",
            keyword=keyword,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return SearchResult(
            status=Status.BLOCKED,
            items=[],
            ms_used=int((time.perf_counter() - started) * 1000),
            hint=f"抖音昵称搜索数据源不可用：{type(exc).__name__}",
            source="tikhub",
            platform="douyin",
            keyword=keyword,
        )

    if payload.get("code") != 200:
        return SearchResult(
            status=Status.BLOCKED,
            items=[],
            ms_used=int((time.perf_counter() - started) * 1000),
            hint="抖音昵称搜索数据源拒绝了请求，请检查本地 API Key 和额度",
            source="tikhub",
            platform="douyin",
            keyword=keyword,
        )

    items: list[dict[str, Any]] = []
    for entry in _users(payload):
        user = entry.get("user_info") if isinstance(entry.get("user_info"), dict) else entry
        sec_uid = str(user.get("sec_uid") or "").strip()
        nickname = str(user.get("nickname") or "").strip()
        if not sec_uid or not nickname:
            continue
        items.append(
            {
                "platform": "douyin",
                "user_id": sec_uid,
                "display_name": nickname,
                "avatar": _avatar(user),
                "fans": int(user.get("follower_count") or 0),
                "canonical_url": f"https://www.douyin.com/user/{sec_uid}",
                "is_live": user.get("live_status") == 1,
                "followers_unknown": False,
            }
        )
        if len(items) >= limit:
            break

    return SearchResult(
        status=Status.SUCCESS if items else Status.EMPTY,
        items=items,
        ms_used=int((time.perf_counter() - started) * 1000),
        hint="",
        source="tikhub",
        platform="douyin",
        keyword=keyword,
    )
