# Gate 1.2-3 — SQLAlchemy UnitOfWork + Transaction Semantics

Status: **PASS / CLOSED**

Entry authority: Gate 1.2-2 PASS.

## 1. Purpose

Gate 1.2-3 introduces the concrete SQLAlchemy implementation of the
`application.ports.UnitOfWork` contract. It turns the four accepted repository
implementations into one explicit application transaction boundary.

Canonical ownership:

```text
application use case
  -> UnitOfWork
      -> one AsyncSession
          -> CreatorRepository
          -> FollowRepository
          -> LiveRepository
          -> NotificationRepository
```

Repositories remain persistence translators only. The UnitOfWork owns commit /
rollback / session lifetime. Provider and network work remains outside this DB
transaction boundary.

## 2. Concrete implementation

Landed implementation:

```text
stage_letter/infrastructure/db/uow.py
```

`SQLAlchemyUnitOfWork` creates one session per entered context and binds all four
repositories to that exact session instance.

Frozen behavior:

```text
enter -> create one AsyncSession + four repositories
commit() -> explicit session.commit()
rollback() -> explicit session.rollback()
normal exit without commit/rollback -> rollback
exceptional exit before commit -> rollback + propagate exception
explicit rollback -> no duplicate rollback on exit
exit -> always close session
nested re-entry while active -> rejected
commit/rollback outside active context -> rejected
```

The UnitOfWork does not auto-commit successful contexts.

## 3. Atomicity scope

The accepted boundary can persist one multi-repository use-case atomically:

```text
LiveObservation
+ LiveSession
+ LiveEvent
+ logical NotificationDelivery when required
+ explicit commit
```

Gate 1.2-3 proves the transaction boundary only; the later state-engine,
scheduler, and notification-runtime gates retain ownership of their semantics.

## 4. First PostgreSQL attempt — real defect found

The first real PostgreSQL probe failed while inserting `LiveEvent` because a
pending ORM `LiveSession` had not been flushed before FK-dependent PostgreSQL
Core DML.

Root cause:

```text
save_session()  -> ORM pending parent
append_event()  -> Core INSERT ... ON CONFLICT
```

This was classified as a real integration defect, not an environment BLOCKED.

## 5. Corrective fix

`SQLAlchemyLiveRepository` now explicitly performs:

```text
await session.flush()
```

before FK-sensitive Core insert paths for observations/events. `flush()` keeps
all writes inside the same transaction and does not commit.

A regression contract protects this ordering requirement.

## 6. Accepted PostgreSQL evidence

Corrected user-local probe:

```text
[uow] database created
...
[uow] head PASS -> c91e8d2f4a10
PASS: Gate 1.2-3 SQLAlchemy UnitOfWork transaction semantics
[cleanup] dropped stageletter_gate12_uow
```

This proves:

```text
one shared AsyncSession for all four repositories
explicit commit persists multi-repository work
normal exit without commit rolls back
exceptional exit rolls back and propagates
FK-sensitive pending ORM parents are flushed safely
probe database cleanup succeeds
```

## 7. Accepted static evidence

User confirmed both post-fix local acceptance commands PASS:

```text
Dedicated UnitOfWork contract suite: PASS / 9 tests
Full Gate 1 suite:                  PASS / 88 tests
```

## 8. Final acceptance

```text
A. Gate 1.2-2 closed PASS                                  PASS
B. concrete UnitOfWork implements formal port              PASS
C. all four repositories share one AsyncSession            PASS
D. explicit commit persists multi-repository work          PASS
E. normal uncommitted exit rolls back                      PASS
F. exceptional exit rolls back and propagates              PASS
G. session always closes                                   PASS
H. UnitOfWork owns no provider/network behavior            PASS
I. FK-sensitive Core inserts flush pending ORM parents     PASS
J. UnitOfWork contract tests                               PASS / 9
K. full Gate 1 suite                                       PASS / 88
L. PostgreSQL UnitOfWork probe                             PASS
```

Gate 1.2-3: **PASS / CLOSED**.

## 9. Preserved constraints

The Gate keeps all prior invariants intact:

```text
no repository-owned commit
no unrelated session inside one UnitOfWork
no implicit auto-commit
no swallowed application exception
no provider/network work inside DB transaction
no legacy runtime imports
no fabricated parent rows
no UNKNOWN -> OFFLINE semantic drift
```
