"""Explicit domain-string <-> PostgreSQL BIGINT identity translation.

Gate 1 domain/application contracts intentionally expose opaque identifiers as
strings. The Gate 1.1 PostgreSQL schema retains BIGINT primary keys for users,
creators, platform accounts, and live sessions. Repository implementations are
the only place allowed to translate between those representations.

The translation is deliberately strict and bijective:

- only canonical positive ASCII decimal strings are accepted;
- leading zeroes, whitespace, signs, Unicode digits, zero, negatives, and
  out-of-range BIGINT values are rejected;
- no hashing, truncation, generated substitute id, or fallback coercion is
  permitted.

Formal string identities that already have dedicated columns (for example
``LiveObservation.observation_id`` and ``LiveEvent.event_id``) are NOT routed
through these helpers and must be persisted verbatim.
"""

from __future__ import annotations


MAX_POSTGRES_BIGINT = (1 << 63) - 1


class PersistenceIdentityError(ValueError):
    """Raised when an opaque domain id cannot map losslessly to a DB BIGINT."""


def parse_persistence_id(value: str, *, field: str) -> int:
    """Convert a canonical positive decimal domain id into a PostgreSQL BIGINT.

    The conversion is intentionally stricter than ``int(value)`` so different
    strings can never alias the same persistence key.
    """

    if not isinstance(value, str):
        raise PersistenceIdentityError(f"{field} must be a string")
    if not value:
        raise PersistenceIdentityError(f"{field} is required")
    if value != value.strip():
        raise PersistenceIdentityError(f"{field} must not contain surrounding whitespace")
    if not value.isascii() or not value.isdecimal():
        raise PersistenceIdentityError(f"{field} must be canonical ASCII decimal")
    if value.startswith("0"):
        raise PersistenceIdentityError(f"{field} must not contain leading zeroes")

    parsed = int(value)
    if parsed < 1 or parsed > MAX_POSTGRES_BIGINT:
        raise PersistenceIdentityError(f"{field} is outside positive PostgreSQL BIGINT range")
    return parsed


def serialize_persistence_id(value: int, *, field: str) -> str:
    """Convert a positive PostgreSQL BIGINT identity into its canonical string."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise PersistenceIdentityError(f"{field} must be an integer")
    if value < 1 or value > MAX_POSTGRES_BIGINT:
        raise PersistenceIdentityError(f"{field} is outside positive PostgreSQL BIGINT range")
    return str(value)
