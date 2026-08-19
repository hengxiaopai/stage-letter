# Gate 1.2-3 — SQLAlchemy UnitOfWork + Transaction Semantics

Status: **CURRENT / CODE + CONTRACTS + POSTGRES PROBE LANDED / LOCAL EVIDENCE PENDING**

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

## 6. Real PostgreSQL probe

Landed:

```text
scripts/gate12_uow_probe.py
```

It creates only:

```text
stageletter_gate12_uow
```

and always attempts cleanup in `finally`.

The probe performs three transaction scenarios against the current Alembic head:

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
one UnitOfWork.

## 7. Acceptance

Gate 1.2-3 PASS requires:

```text
A. Gate 1.2-2 closed PASS                                  PASS
B. concrete UnitOfWork implements formal port              CODE LANDED
C. all four repositories share one AsyncSession            CONTRACT + PROBE LANDED
D. explicit commit persists multi-repository work          PROBE LANDED
E. normal uncommitted exit rolls back                      CONTRACT + PROBE LANDED
F. exceptional exit rolls back and propagates              CONTRACT + PROBE LANDED
G. session always closes                                   CONTRACT LANDED
H. UnitOfWork owns no provider/network behavior            CONTRACT LANDED
I. UnitOfWork contract tests pass                          PENDING LOCAL EVIDENCE
J. full Gate 1 suite remains green                         PENDING LOCAL EVIDENCE
K. PostgreSQL UnitOfWork probe passes                      PENDING LOCAL EVIDENCE
```

Gate 1.2-3 remains **CURRENT** until I-K pass.

## 8. Stop rules

Stop with FAIL/BLOCKED if acceptance would require:

```text
repository-owned commit
multiple unrelated sessions inside one UnitOfWork
implicit auto-commit on context success
swallowing application exceptions
provider/network calls inside the DB transaction
legacy runtime imports
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```
