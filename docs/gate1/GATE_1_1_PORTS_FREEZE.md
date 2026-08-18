# Gate 1.1-2 — Repository / Application Ports Freeze

Status: **PASS**

## Purpose

Freeze the application-facing persistence boundary before SQLAlchemy models or Alembic migrations are written.

The application layer depends on protocols; infrastructure implements them later.

```text
api/workers -> application -> domain
                    ^
                    |
             infrastructure implements ports
```

## Frozen repository ports

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
UnitOfWork
```

Key semantic boundaries:

```text
CreatorRepository owns Creator / CreatorProfile / PlatformAccount persistence.
FollowRepository keeps Follow and NotificationPreference as separate facts.
LiveRepository persists LiveObservation as first-class evidence before session/event outputs.
NotificationRepository addresses logical deliveries by DeliveryKey(user_id, live_event_id, channel).
UnitOfWork provides the atomic transaction boundary required by Gate 0B restart/atomicity semantics.
```

All persistence I/O methods are async contracts. No SQLAlchemy/Redis/FastAPI/Dramatiq/provider dependency is allowed in these ports.

## Explicit non-goals

1. No SQLAlchemy implementation in the application package.
2. No Alembic migration in 1.1-2.
3. No Redis/Dramatiq queue contract yet.
4. No provider-specific WeChat methods in repository ports.
5. No direct runtime import from `experiments/*`.
6. No persistence method that treats timeout/parse/provider failure as OFFLINE truth.

## Acceptance evidence

Local evidence supplied on 2026-08-18:

```text
python -m unittest discover -s tests/gate1 -p "test_*.py" -v
Ran 17 tests in 0.002s
OK
```

The original text grep dependency check produced a false positive because the module docstring explicitly names the forbidden frameworks it avoids, and `__pycache__` was also scanned. That result is not treated as a code failure.

A Python AST import audit was then run against `stage_letter/domain` and `stage_letter/application` and returned:

```text
PASS: domain/application contain no forbidden runtime imports
```

A separate experiment-import check returned:

```text
PASS: no experiments runtime imports
```

## Acceptance

```text
A. application package exists                                  PASS
B. repository ports are Protocol contracts                    PASS
C. persistence I/O is async                                   PASS
D. LiveObservation has a first-class persistence method       PASS
E. Follow and NotificationPreference remain separate          PASS
F. delivery lookup/create is event-key based                  PASS
G. explicit UnitOfWork commit/rollback boundary exists        PASS
H. no forbidden infrastructure dependency in application     PASS
I. local contract tests pass: 17/17                           PASS
```

Decision:

```text
Gate 1.1-2 PASS
Gate 1.1-3 READY — SQLAlchemy Persistence Models
```
