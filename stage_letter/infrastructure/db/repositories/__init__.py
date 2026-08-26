"""SQLAlchemy repository implementations for formal Stage Letter runtime.

Gate 1.2 keeps persistence translation here. Business transitions, notification
eligibility, provider calls, and transaction commits do not belong in
repository classes.
"""

from .common import RepositoryMappingError
from .creator import SQLAlchemyCreatorRepository
from .follow import SQLAlchemyFollowRepository
from .grant import SQLAlchemyGrantRepository
from .identity import (
    MAX_POSTGRES_BIGINT,
    PersistenceIdentityError,
    parse_persistence_id,
    serialize_persistence_id,
)
from .live import SQLAlchemyLiveRepository
from .notification import SQLAlchemyNotificationRepository
from .personal_streamer_profile import SQLAlchemyPersonalStreamerProfileRepository
from .session_insights import SQLAlchemySessionInsightRepository
from .wechat_template import SQLAlchemyWeChatTemplateRepository

__all__ = [
    "MAX_POSTGRES_BIGINT",
    "PersistenceIdentityError",
    "RepositoryMappingError",
    "SQLAlchemyCreatorRepository",
    "SQLAlchemyFollowRepository",
    "SQLAlchemyGrantRepository",
    "SQLAlchemyLiveRepository",
    "SQLAlchemyNotificationRepository",
    "SQLAlchemyPersonalStreamerProfileRepository",
    "SQLAlchemySessionInsightRepository",
    "SQLAlchemyWeChatTemplateRepository",
    "parse_persistence_id",
    "serialize_persistence_id",
]
