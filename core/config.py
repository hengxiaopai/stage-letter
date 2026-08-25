"""StageLetter 配置中心(Gate 1 骨架)。

环境变量全部带 STAGE_LETTER_ 前缀,避免与其他项目冲突。
所有值都可以被环境变量覆盖。
支持从项目根目录 .env 文件加载(不覆盖已存在的环境变量)。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent

# 加载 .env(如有);不覆盖已存在的环境变量
_ENV_FILE = ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v


def _env(name: str, default: str) -> str:
    return os.environ.get(f"STAGE_LETTER_{name}", default)


class Settings:
    # ── 基础 ──
    app_name: str = "StageLetter"
    debug: bool = _env("DEBUG", "false").lower() == "true"
    log_level: str = _env("LOG_LEVEL", "INFO")

    # ── 数据库(PostgreSQL)──
    # 本机已有 postgres 占 5432,开发容器映射 5433(见 docker-compose.yml)
    database_url: str = _env(
        "DATABASE_URL",
        "postgresql+asyncpg://stageletter:stageletter@localhost:5433/stageletter",
    )

    # ── Redis(队列 / 缓存)──
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")

    # ── 微信小程序(正式号,Gate 0A 已实测)──
    wx_appid: str = _env("WX_APPID", "")
    wx_secret: str = _env("WX_SECRET", "")
    wx_template_live_start: str = _env("WX_TEMPLATE_LIVE_START", "")

    # Optional commercial lookup source for Douyin nickname -> sec_uid.
    # Keep compatibility with the Gate 0A experiment's unprefixed local key.
    tikhub_api_key: str = os.environ.get("TIKHUB_API_KEY", "").strip() or _env("TIKHUB_API_KEY", "")

    # ── Internal admin (Gate 5; configure only in local/deployed secrets) ──
    admin_username: str = _env("ADMIN_USERNAME", "")
    admin_password: str = _env("ADMIN_PASSWORD", "")

    # ── 轮询 ──
    probe_min_interval_s: float = float(_env("PROBE_MIN_INTERVAL", "3"))
    probe_default_timeout_s: float = float(_env("PROBE_TIMEOUT", "8"))

    # ── 风控退避(Gate 0C 实测后会调参)──
    ratelimit_backoff_min_s: int = int(_env("RATELIMIT_BACKOFF_MIN", "1800"))
    ratelimit_backoff_max_s: int = int(_env("RATELIMIT_BACKOFF_MAX", "86400"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
