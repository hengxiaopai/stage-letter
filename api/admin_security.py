"""Server-side operator boundary for the Gate 5 Admin surface."""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from core.config import settings


_basic_auth = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class AdminActor:
    username: str


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_basic_auth),
) -> AdminActor:
    """Require configured operator credentials; never fall back to anonymous access."""

    username = settings.admin_username
    password = settings.admin_password
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin access is not configured",
        )
    if credentials is None or not (
        secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return AdminActor(username=username)
