"""SQLAlchemy UnitOfWork for the formal Stage Letter runtime.

The UnitOfWork owns one AsyncSession boundary and exposes all four formal
repositories over that same session. Repository methods never commit; the
application layer explicitly chooses commit or rollback through this object.
"""
from __future__ import annotations

from types import TracebackType
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from .repositories import (
    SQLAlchemyCreatorRepository,
    SQLAlchemyFollowRepository,
    SQLAlchemyLiveRepository,
    SQLAlchemyNotificationRepository,
)


SessionFactory = Callable[[], AsyncSession]


class SQLAlchemyUnitOfWork:
    """Concrete transaction boundary implementing ``application.ports.UnitOfWork``.

    Semantics:
    - one AsyncSession is created per entered context;
    - all repositories share that exact session;
    - commit is explicit;
    - an exception, or a normal exit without commit, rolls back;
    - the session is always closed on exit;
    - external provider/network work does not belong in this boundary.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None
        self.creators: SQLAlchemyCreatorRepository | None = None
        self.follows: SQLAlchemyFollowRepository | None = None
        self.live: SQLAlchemyLiveRepository | None = None
        self.notifications: SQLAlchemyNotificationRepository | None = None
        self._committed = False

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        if self.session is not None:
            raise RuntimeError("UnitOfWork is already active")

        session = self._session_factory()
        self.session = session
        self.creators = SQLAlchemyCreatorRepository(session)
        self.follows = SQLAlchemyFollowRepository(session)
        self.live = SQLAlchemyLiveRepository(session)
        self.notifications = SQLAlchemyNotificationRepository(session)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        session = self._require_session()
        try:
            if exc_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self.session = None
            self.creators = None
            self.follows = None
            self.live = None
            self.notifications = None
            self._committed = False
        return False

    async def commit(self) -> None:
        session = self._require_session()
        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        session = self._require_session()
        await session.rollback()
        self._committed = False

    def _require_session(self) -> AsyncSession:
        if self.session is None:
            raise RuntimeError("UnitOfWork must be used inside 'async with'")
        return self.session
