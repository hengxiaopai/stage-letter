"""认证路由:微信登录 + 会话。

POST /api/v1/auth/login   {code} → {user_id, openid, is_new}

当前返回完整 openid 供 Gate 4 开发联调；生产仍需改为服务端会话 token。
登录失败必须显式返回错误，不能用伪造 openid 静默降级。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wechat import WeChatError, get_wechat_client
from core.config import settings
from core.db import get_db
from core.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("code must not be blank")
        return value


class LoginResponse(BaseModel):
    user_id: int
    openid: str  # dev: 完整 openid;生产: 建议改 token + tail
    openid_tail: str
    is_new: bool
    live_start_template_id: str | None = None


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """wx.login code → openid → 获取或创建 user。"""
    try:
        info = get_wechat_client().code2session(req.code)
        openid = info["openid"]
        unionid = info.get("unionid")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="微信登录服务配置不完整") from exc
    except WeChatError as exc:
        raise HTTPException(status_code=400, detail="微信登录凭证无效或已失效") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="微信登录服务暂时不可用，请重试") from exc

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
        live_start_template_id=settings.wx_template_live_start.strip() or None,
    )
