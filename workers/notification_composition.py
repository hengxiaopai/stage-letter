"""Composition root for the formal multi-channel notification runtimes.

It is intentionally separate from ``workers/composition.py`` so Gate 1.4's
live-monitoring composition freeze remains unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork
from stage_letter.infrastructure.notifications.wechat import (
    HttpxWeChatProviderGateway,
    WeChatSubscribeFormalAdapter,
)
from workers.notification_runtime import (
    InAppNotificationRuntime,
    WeChatNotificationRuntime,
)


@dataclass(frozen=True)
class WeChatNotificationRuntimeBundle:
    runtime: WeChatNotificationRuntime


@dataclass(frozen=True)
class InAppNotificationRuntimeBundle:
    runtime: InAppNotificationRuntime


def build_in_app_notification_runtime(
    session_factory: async_sessionmaker[AsyncSession],
) -> InAppNotificationRuntimeBundle:
    """Build the DB-only in-app publisher without provider configuration."""

    def uow_factory():
        return SQLAlchemyUnitOfWork(session_factory)

    return InAppNotificationRuntimeBundle(
        runtime=InAppNotificationRuntime(uow_factory=uow_factory)
    )


def build_wechat_notification_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    appid: str,
    app_secret: str,
    template_id: str,
    http_client: httpx.AsyncClient,
) -> WeChatNotificationRuntimeBundle:
    """Build runtime lazily; construction performs no DB or provider request."""

    def uow_factory():
        return SQLAlchemyUnitOfWork(session_factory)

    gateway = HttpxWeChatProviderGateway(
        appid=appid,
        app_secret=app_secret,
        client=http_client,
    )
    provider = WeChatSubscribeFormalAdapter(gateway)
    runtime = WeChatNotificationRuntime(
        uow_factory=uow_factory,
        session_factory=session_factory,
        provider=provider,
        template_id=template_id,
    )
    return WeChatNotificationRuntimeBundle(runtime=runtime)
