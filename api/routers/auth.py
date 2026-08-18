"""认证路由:微信登录 + 会话。

POST /api/v1/auth/login   {code} → {user_id, openid, is_new}

Dev 模式(DEBUG=true):
- code 无效时(开发者工具/本地联调,微信 code 不可用)自动降级:
  用 code 的 hash 生成确定性 openid `dev_<hash>`,保证本地联调可用
- 返回完整 openid(生产建议改为只返回 tail + token)
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wechat import WeChatError, get_wechat_client
from core.config import settings
from core.db import get_db
from core.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    code: str


class LoginResponse(BaseModel):
    user_id: int
    openid: str  # dev: 完整 openid;生产: 建议改 token + tail
    openid_tail: str
    is_new: bool


def _dev_openid(code: str) -> str:
    """Dev 降级: 用 code 生成确定性 openid(本地联调用)。"""
    digest = hashlib.sha256(code.encode()).hexdigest()[:28]
    return f"dev_{digest}"


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """wx.login code → openid → 获取或创建 user。"""
    openid = None
    unionid = None

    try:
        info = get_wechat_client().code2session(req.code)
        openid = info["openid"]
        unionid = info.get("unionid")
    except WeChatError as e:
        if settings.debug:
            # Dev 模式: code2session 不可用(假 code),降级为确定性 openid
            openid = _dev_openid(req.code)
            unionid = None
        else:
            raise HTTPException(status_code=400, detail=f"code2session failed: {e.errmsg}")

    result = await db.execute(select(User).where(User.openid == openid))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            openid=openid,
            unionid=unionid,
            nickname=None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        is_new = True
    else:
        is_new = False

    return LoginResponse(
        user_id=user.id,
        openid=openid,
        openid_tail=openid[-4:],
        is_new=is_new,
    )
