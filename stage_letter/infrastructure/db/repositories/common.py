"""Shared safeguards for formal SQLAlchemy repositories."""
from __future__ import annotations


class RepositoryMappingError(RuntimeError):
    """Raised when persisted legacy truth cannot map to a formal domain object.

    Gate 1 forbids inventing event cause, session origin, or other missing facts
    just to make an ORM row fit the formal domain vocabulary.
    """
