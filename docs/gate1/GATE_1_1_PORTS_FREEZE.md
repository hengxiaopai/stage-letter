# Gate 1.1-2 — Repository / Application Ports Freeze

Status: **CURRENT / CODE LANDED, TEST EVIDENCE PENDING**

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

1. No SQLAlchemy implementation yet.
2. No Alembic migration yet.
3. No Redis/Dramatiq queue contract yet.
4. No provider-specific WeChat methods in repository ports.
5. No direct import from `experiments/*`.
6. No persistence method that treats timeout/parse/provider failure as OFFLINE truth.

## Acceptance

```text
A. application package exists                                  CODE PASS
B. repository ports are Protocol contracts                    CODE PASS
C. persistence I/O is async                                   CODE PASS
D. LiveObservation has a first-class persistence method       CODE PASS
E. Follow and NotificationPreference remain separate          CODE PASS
F. delivery lookup/create is event-key based                  CODE PASS
G. explicit UnitOfWork commit/rollback boundary exists        CODE PASS
H. no forbidden infrastructure dependency in application     PENDING EVIDENCE
I. local/CI contract tests pass                                PENDING EVIDENCE
```

After H-I pass, Gate 1.1-2 may close and Gate 1.1-3 can start SQLAlchemy persistence models.
