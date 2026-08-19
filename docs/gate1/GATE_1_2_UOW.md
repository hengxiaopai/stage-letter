# Gate 1.2-3 — SQLAlchemy UnitOfWork + Transaction Semantics

Status: **CURRENT / CORRECTED POSTGRES PROBE PASS / STATIC ACCEPTANCE PENDING**

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

`SQLAlchemyUnitOfWork` accepts a session factory and, on each entered context,
creates exactly one session. All four repositories are bound to that exact
session instance.

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

The UnitOfWork does not auto-commit successful contexts. Application services
must request commit explicitly.

## 3. Atomicity scope

Gate 0B established that one live observation may cause canonical session/event
changes that must survive restart atomically. Gate 1.2-3 therefore preserves the
ability for a later application service to perform:

```text
append LiveObservation
+ save/update LiveSession
+ append LiveEvent
+ create logical NotificationDelivery when the use case requires it
+ explicit commit
```

through one shared transaction.

This slice does not yet migrate the Gate 0 state engine into a formal application
service; that belongs to Gate 1.2-4 and later Gate 1.4/1.5 work. Gate 1.2-3 only
proves the transaction boundary required by those services.

## 4. Provider/network boundary

No external provider/network call may be hidden inside this UnitOfWork merely
for convenience.

Required order for later notification flows remains conceptually:

```text
DB transaction creates/persists logical work
-> commit
-> queue/provider runtime performs external send in its own controlled phase
```

Gate 0D's `IN_FLIGHT` / `AMBIGUOUS` semantics remain authoritative for the later
notification runtime gate.

## 5. Contract tests

Landed:

```text
tests/gate1/test_uow_contract.py
```

The tests verify:

```text
structural UnitOfWork port compatibility
one shared session across all four repositories
explicit commit delegation
implicit rollback on uncommitted normal exit
rollback + exception propagation on exceptional exit
explicit rollback is not repeated
active-context requirement
nested re-entry rejection
no transport/provider/legacy imports
```

## 6. First PostgreSQL attempt — FAILED, root cause identified

The first real PostgreSQL probe reached the current Alembic head and then failed
inside the COMMIT scenario while appending a `LiveEvent`:

```text
ForeignKeyViolationError:
live_events.live_session_id = 300
but live_sessions.id = 300 was not yet visible to PostgreSQL
```

The shared UnitOfWork session was correct. The failure was caused by mixed SQLAlchemy
write modes inside the same transaction:

```text
save_session()
  -> ORM pending LiveSessionModel (session.add)

append_event()
  -> PostgreSQL Core INSERT ... ON CONFLICT
```

A Core DML execution did not provide the ORM dependency ordering guarantee that
this write path needed. The pending parent `LiveSession` had not been flushed
before the FK-constrained Core `live_events` INSERT.

This was a real Gate 1.2-3 integration defect, not an environment failure. The
probe correctly stopped and cleaned up its temporary database.

## 7. Corrective fix — PASS IN REAL POSTGRESQL

`SQLAlchemyLiveRepository` now explicitly calls:

```text
await session.flush()
```

before the two FK-sensitive Core INSERT paths:

```text
append_observation()
append_event()
```

This guarantees that pending ORM parent rows (for example a newly-added
`PlatformAccount` or `LiveSession`) reach PostgreSQL before dependent Core DML.
`flush()` does **not** commit; the enclosing UnitOfWork still owns the single
atomic transaction.

A regression contract was added to ensure these two paths retain the flush
boundary.

The UnitOfWork's explicit rollback bookkeeping also remains aligned with the
frozen rule that an explicit rollback is not repeated again on context exit.

## 8. Real PostgreSQL probe — PASS

Probe:

```text
scripts/gate12_uow_probe.py
```

It creates only:

```text
stageletter_gate12_uow
```

and always attempts cleanup in `finally`.

Accepted user-local evidence after the corrective flush fix:

```text
[uow] database created
...
[uow] head PASS -> c91e8d2f4a10
PASS: Gate 1.2-3 SQLAlchemy UnitOfWork transaction semantics
[cleanup] dropped stageletter_gate12_uow
```

The corrected probe therefore proves all three transaction scenarios:

```text
COMMIT
  multi-repository canonical writes
  -> explicit commit
  -> all facts persisted

NORMAL EXIT WITHOUT COMMIT
  canonical writes
  -> context exit
  -> all facts rolled back

EXCEPTIONAL EXIT
  canonical write
  -> induced application exception
  -> write rolled back
  -> exception propagated
```

It also proves all four concrete repositories share the same AsyncSession inside
one UnitOfWork and that the temporary database is cleaned up.

## 9. Acceptance

Gate 1.2-3 PASS requires:

```text
A. Gate 1.2-2 closed PASS                                  PASS
B. concrete UnitOfWork implements formal port              PASS / code landed
C. all four repositories share one AsyncSession            PASS / real DB probe
D. explicit commit persists multi-repository work          PASS / real DB probe
E. normal uncommitted exit rolls back                      PASS / real DB probe
F. exceptional exit rolls back and propagates              PASS / real DB probe
G. session always closes                                   CONTRACT LANDED
H. UnitOfWork owns no provider/network behavior            CONTRACT LANDED
I. FK-sensitive Core inserts flush pending ORM parents     PASS / real DB probe
J. UnitOfWork contract tests pass                          PENDING LOCAL EVIDENCE
K. full Gate 1 suite remains green                         PENDING LOCAL EVIDENCE
L. PostgreSQL UnitOfWork probe passes                      PASS
```

Gate 1.2-3 remains **CURRENT** until J-K pass.

## 10. Stop rules

Stop with FAIL/BLOCKED if acceptance would require:

```text
repository-owned commit
multiple unrelated sessions inside one UnitOfWork
implicit auto-commit on context success
swallowing application exceptions
provider/network calls inside the DB transaction
legacy runtime imports
manual fake parent rows to satisfy foreign keys
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```
