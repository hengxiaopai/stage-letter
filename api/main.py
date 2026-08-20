"""StageLetter API 入口(Gate 1 骨架)。

路由:
  GET  /health                       健康检查
  POST /api/v1/auth/login            微信登录
  POST /api/v1/anchors/parse         粘贴 URL 解析主播
  GET  /api/v1/anchors/{id}          主播详情
  POST /api/v1/subscriptions         订阅主播
  GET  /api/v1/lives/active          我订阅的正在直播
  GET  /api/v1/lives/recent          最近开播
  GET  /api/v1/notifications/grants  grant 余额
  POST /api/v1/notifications/request-grant  记录授权
  GET  /api/v1/notifications/history 通知历史
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from api.composition import build_api_services
from api.routers import anchors, auth, health, lives, notifications, subscriptions
from core.config import settings
from core.db import async_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stage-letter")

app = FastAPI(
    title=settings.app_name,
    version="0.3.8",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# Gate 1.2 composition seam. Existing legacy routers remain operational during
# staged cutover, while new/formal handlers must resolve orchestration through
# this application-service bundle rather than owning domain rules themselves.
app.state.stage_letter_services = build_api_services(async_session)


@app.get("/health")
async def ping() -> dict:
    return {"status": "ok", "app": settings.app_name}


# API 路由
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(anchors.router, prefix="/api/v1", tags=["anchors"])
app.include_router(subscriptions.router, prefix="/api/v1", tags=["subscriptions"])
app.include_router(lives.router, prefix="/api/v1", tags=["lives"])
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
