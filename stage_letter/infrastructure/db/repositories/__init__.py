"""SQLAlchemy repository implementations for formal Stage Letter runtime.

Gate 1.2 keeps persistence translation here. Business transitions, notification
eligibility, provider calls, and transaction commits do not belong in
repository classes.
"""

from .identity import (
    MAX_POSTGRES_BIGINT,
    PersistenceIdentityError,
    parse_persistence_id,
    serialize_persistence_id,
)

__all__ = [
    "MAX_POSTGRES_BIGINT",
    "PersistenceIdentityError",
    "parse_persistence_id",
    "serialize_persistence_id",
]
