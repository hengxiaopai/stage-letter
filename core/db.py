"""数据库连接(Gate 1 骨架,SQLAlchemy 2.x async)。

生产用 PostgreSQL + asyncpg;测试可用 sqlite(需调整部分 PG 特定类型)。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI 依赖:请求级 session。"""
    async with async_session() as session:
        yield session
