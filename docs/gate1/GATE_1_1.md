# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PASS / 1.1-2 PORTS CODE LANDED**

Entry authority: Gate 1.0 PASS.

Detailed ports freeze: [`GATE_1_1_PORTS_FREEZE.md`](./GATE_1_1_PORTS_FREEZE.md).

## 1. Purpose

Gate 1.1 turns the accepted Gate 0 semantics into formal V0.1 domain types, persistence contracts, SQLAlchemy models, and forward-only PostgreSQL migrations without inventing historical truth.

Execution order is frozen:

```text
1. pure domain types + invariants
2. formal semantic tests
3. repository/application ports
4. SQLAlchemy persistence models
5. Alembic EXPAND migration
6. deterministic backfill
7. DB constraints/indexes
8. clean-database migration test
9. representative legacy-dataset upgrade test
10. Gate 0 regression/golden-path comparison
```

## 2. Gate 1.1-1 — Pure Domain — PASS

Formal domain package:

```text
stage_letter/domain/
  creators.py
  follows.py
  live.py
  notifications.py
  health.py
```

Frozen invariants:

```text
LiveObservation.status = LIVE | OFFLINE | UNKNOWN
UNKNOWN != OFFLINE
Creator != PlatformAccount
one Creator may own N PlatformAccounts
Follow != NotificationPreference
LiveEvent = event_type + cause
LIVE_STARTED + BOOTSTRAP_LIVE != LIVE_STARTED + TRANSITION
logical delivery identity = (user_id, live_event_id, channel)
AMBIGUOUS is first-class and forbids blind retry
SENT is terminal for one logical delivery only
runtime health = STARTING | HEALTHY | DEGRADED | UNAVAILABLE
admin enabled/disabled is configuration, not runtime health
```

### 1.1-1 acceptance evidence

User-local execution on 2026-08-18:

```text
python -m unittest discover -s tests/gate1 -p "test_*.py" -v
Ran 11 tests in 0.002s
OK
```

Pure-domain dependency audit:

```text
grep -RniE 'sqlalchemy|fastapi|redis|dramatiq|experiments.' stage_letter/domain
PASS: pure domain has no forbidden runtime dependency
```

Acceptance:

```text
A. stage_letter/domain package exists                         PASS
B. ten formal entity boundaries represented                  PASS
C. canonical live status exactly LIVE/OFFLINE/UNKNOWN        PASS
D. delivery identity event-based                             PASS
E. delivery runtime includes AMBIGUOUS                       PASS
F. no forbidden infrastructure imports                       PASS
G. formal domain contract tests added                        PASS
H. local test evidence                                       PASS
```

Gate 1.1-1: **PASS**.

## 3. Gate 1.1-2 — Repository / Application Ports — CURRENT

Formal application port package has landed:

```text
stage_letter/application/
  __init__.py
  ports.py
```

Frozen ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
UnitOfWork
```

Semantic requirements:

```text
Creator/Profile/PlatformAccount persistence stays distinct.
Follow and NotificationPreference persistence stays distinct.
LiveObservation is persisted as first-class evidence.
Session/Event writes are behind the same live persistence boundary.
NotificationDelivery lookup/create is keyed by DeliveryKey(user_id, live_event_id, channel).
UnitOfWork is the formal atomic commit/rollback boundary.
All repository I/O is async.
```

Contract tests are in `tests/gate1/test_application_ports.py`.

Gate 1.1-2 cannot be marked PASS until local/CI evidence confirms:

```text
repository/application contract tests pass
stage_letter/application has no SQLAlchemy/FastAPI/Redis/Dramatiq/experiments runtime import
```

## 4. Gate 1.1 remaining plan

After 1.1-2 PASS:

```text
1.1-3 SQLAlchemy persistence models
1.1-4 Alembic EXPAND migration + deterministic backfill rules
1.1-5 DB constraints + clean/legacy migration tests
1.1-6 Gate 0 regression and golden-path comparison
```

No SQLAlchemy model or migration is accepted before the port boundary is verified.

## 5. Stop rules

Gate 1.1 must stop with FAIL/BLOCKED if any implementation requires:

```text
UNKNOWN -> OFFLINE
fabricated LiveObservation history
fabricated source_started_at
invented BOOTSTRAP vs TRANSITION cause
session-based delivery idempotency
blind resend from AMBIGUOUS
SENT -> global grant exhaustion inference
provider/notification failure -> creator live truth mutation
```

## 6. Current progression

```text
Gate 1.0    PASS
Gate 1.1-1  PASS / pure domain + 11/11 local evidence
Gate 1.1-2  CURRENT / repository + UnitOfWork ports landed; evidence pending
Gate 1.1-3  NOT STARTED
Gate 1.1    CURRENT
```
