"""Protected, read-only Gate 5.1 operator health surface."""
from __future__ import annotations

from html import escape
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin_security import AdminActor, require_admin
from api.routers.health import build_system_health
from api.services.admin_inquiry import (
    DEFAULT_PAGE_SIZE,
    list_deliveries,
    list_subscriptions,
    list_users,
    page_payload,
)
from api.services.admin_metrics import build_admin_metrics
from api.services.admin_platforms import PlatformControlAction, apply_platform_control
from core.db import get_db


router = APIRouter()


def _cell(value: object) -> str:
    return escape("—" if value is None else str(value))


def render_admin_health_page(snapshot: dict[str, Any], actor: AdminActor) -> str:
    """Render a dependency-free operator page from an already-authorized snapshot."""

    platforms = snapshot.get("platforms", {})
    rows = "".join(
        "<tr>"
        f"<td>{_cell(platform)}</td>"
        f"<td>{_cell(health.get('state'))}</td>"
        f"<td>{_cell(health.get('consecutive_failures'))}</td>"
        f"<td>{_cell(health.get('success_count_24h'))}</td>"
        f"<td>{_cell(health.get('error_count_24h'))}</td>"
        f"<td>{_cell(health.get('avg_latency_ms_24h'))}</td>"
        "<td>"
        f"<form style='display:inline' method='post' action='/admin/platforms/{_cell(platform)}/disable' onsubmit=\"return confirm('确认禁用该平台检测？')\"><button>禁用</button></form> "
        f"<form style='display:inline' method='post' action='/admin/platforms/{_cell(platform)}/enable' onsubmit=\"return confirm('确认以谨慎恢复方式启用该平台？')\"><button>恢复</button></form>"
        "</td>"
        "</tr>"
        for platform, health in sorted(platforms.items())
    ) or "<tr><td colspan='6'>暂无平台健康记录</td></tr>"
    return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><title>StageLetter Admin</title>
<style>body{{font-family:system-ui;margin:2rem;color:#172a35}}table{{border-collapse:collapse;width:100%;max-width:960px}}th,td{{border:1px solid #d8e0e4;padding:.6rem;text-align:left}}th{{background:#edf5f7}}code{{background:#f3f5f6;padding:.15rem .3rem}}</style>
</head><body><h1>StageLetter Admin</h1><p>已认证操作员：<code>{_cell(actor.username)}</code></p>
<p>API：<strong>{_cell(snapshot.get('api'))}</strong>；Worker healthy：<strong>{_cell(snapshot.get('worker', {}).get('healthy'))}</strong>；更新时间：<code>{_cell(snapshot.get('timestamp'))}</code></p>
<h2>平台健康</h2><table><thead><tr><th>平台</th><th>状态</th><th>连续失败</th><th>24h 成功</th><th>24h 错误</th><th>平均延迟 ms</th><th>受控操作</th></tr></thead><tbody>{rows}</tbody></table>
<p>恢复会进入 DEGRADED，需后续成功探测才会变为 HEALTHY；页面不提供通知操作。</p></body></html>"""


def _rows(items: list[dict], fields: tuple[str, ...]) -> str:
    return "".join(
        "<tr>" + "".join(f"<td>{_cell(item.get(field))}</td>" for field in fields) + "</tr>"
        for item in items
    ) or f"<tr><td colspan='{len(fields)}'>暂无记录</td></tr>"


def render_admin_inquiry_page(
    *, actor: AdminActor, users: dict, subscriptions: dict, deliveries: dict
) -> str:
    """Render a bounded, sanitized read-only inquiry page."""

    user_rows = _rows(users["items"], ("id", "created_at", "last_active_at", "subscription_count"))
    subscription_rows = _rows(
        subscriptions["items"],
        ("id", "user_id", "creator_id", "display_name", "platform", "notify_enabled", "created_at"),
    )
    delivery_rows = _rows(
        deliveries["items"],
        ("id", "user_id", "channel", "state", "attempt", "error_code", "sent_at", "created_at"),
    )
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>StageLetter Admin Inquiry</title>
<style>body{{font-family:system-ui;margin:2rem;color:#172a35}}table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{border:1px solid #d8e0e4;padding:.45rem;text-align:left}}th{{background:#edf5f7}}code{{background:#f3f5f6;padding:.15rem .3rem}}</style>
</head><body><h1>StageLetter Admin Inquiry</h1><p>已认证操作员：<code>{_cell(actor.username)}</code>；每类最多显示 {DEFAULT_PAGE_SIZE} 条。</p>
<h2>用户摘要</h2><table><thead><tr><th>ID</th><th>创建时间</th><th>最近活跃</th><th>订阅数</th></tr></thead><tbody>{user_rows}</tbody></table>
<h2>订阅</h2><table><thead><tr><th>ID</th><th>用户 ID</th><th>创作者 ID</th><th>主播</th><th>平台</th><th>提醒启用</th><th>创建时间</th></tr></thead><tbody>{subscription_rows}</tbody></table>
<h2>投递</h2><table><thead><tr><th>ID</th><th>用户 ID</th><th>渠道</th><th>状态</th><th>尝试</th><th>错误码</th><th>发送时间</th><th>创建时间</th></tr></thead><tbody>{delivery_rows}</tbody></table>
<p>本页不展示 openid、模板、canonical URL 或原始错误文本；不提供发送、重试、删除或状态修改。</p></body></html>"""


def render_admin_metrics_page(*, actor: AdminActor, metrics: dict) -> str:
    """Render bounded operational counters, never individual delivery data."""

    platform_rows = _rows(metrics["platform_health_24h"], ("platform", "success_count_24h", "error_count_24h"))
    delivery_rows = _rows(metrics["deliveries_by_channel_state"], ("channel", "state", "count"))
    error_rows = _rows(metrics["delivery_errors_by_code"], ("error_code", "count"))
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>StageLetter Admin Metrics</title>
<style>body{{font-family:system-ui;margin:2rem;color:#172a35}}table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{border:1px solid #d8e0e4;padding:.45rem;text-align:left}}th{{background:#edf5f7}}code{{background:#f3f5f6;padding:.15rem .3rem}}</style>
</head><body><h1>StageLetter Admin Metrics</h1><p>已认证操作员：<code>{_cell(actor.username)}</code>；所有维度均为固定词表，未知值归入 <code>OTHER</code>。</p>
<h2>平台探测（24h）</h2><table><thead><tr><th>平台</th><th>成功</th><th>错误</th></tr></thead><tbody>{platform_rows}</tbody></table>
<h2>投递（渠道 / 状态）</h2><table><thead><tr><th>渠道</th><th>状态</th><th>数量</th></tr></thead><tbody>{delivery_rows}</tbody></table>
<h2>投递错误（固定错误码）</h2><table><thead><tr><th>错误码</th><th>数量</th></tr></thead><tbody>{error_rows}</tbody></table>
<p>本页不显示用户、主播、OpenID、URL、投递 ID 或原始错误文本；不提供任何写操作。</p></body></html>"""


@router.get("/admin/health")
async def admin_health_snapshot(
    _: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await build_system_health(db)


@router.get("/admin", response_class=HTMLResponse)
async def admin_health_page(
    actor: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    return HTMLResponse(render_admin_health_page(await build_system_health(db), actor))


@router.get("/admin/users")
async def admin_users(
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    _: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return page_payload(await list_users(db, limit=limit, cursor=cursor))


@router.get("/admin/subscriptions")
async def admin_subscriptions(
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    _: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return page_payload(await list_subscriptions(db, limit=limit, cursor=cursor))


@router.get("/admin/deliveries")
async def admin_deliveries(
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    _: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return page_payload(await list_deliveries(db, limit=limit, cursor=cursor))


@router.get("/admin/inquiry", response_class=HTMLResponse)
async def admin_inquiry_page(
    actor: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    users, subscriptions, deliveries = await list_users(db), await list_subscriptions(db), await list_deliveries(db)
    return HTMLResponse(
        render_admin_inquiry_page(
            actor=actor,
            users=page_payload(users),
            subscriptions=page_payload(subscriptions),
            deliveries=page_payload(deliveries),
        )
    )


@router.get("/admin/metrics")
async def admin_metrics_snapshot(
    _: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await build_admin_metrics(db)


@router.get("/admin/metrics/page", response_class=HTMLResponse)
async def admin_metrics_page(
    actor: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    return HTMLResponse(render_admin_metrics_page(actor=actor, metrics=await build_admin_metrics(db)))


async def _control_platform(
    platform: str,
    action: PlatformControlAction,
    actor: AdminActor,
    db: AsyncSession,
) -> RedirectResponse:
    await apply_platform_control(
        db,
        actor_username=actor.username,
        platform=platform,
        action=action,
    )
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/platforms/{platform}/disable")
async def disable_platform(
    platform: str,
    actor: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _control_platform(platform, PlatformControlAction.DISABLE, actor, db)


@router.post("/admin/platforms/{platform}/enable")
async def enable_platform(
    platform: str,
    actor: AdminActor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _control_platform(platform, PlatformControlAction.ENABLE, actor, db)
