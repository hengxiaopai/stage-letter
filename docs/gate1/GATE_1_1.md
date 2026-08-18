# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 CODE COMPLETE, TEST EVIDENCE PENDING**

Entry authority: Gate 1.0 PASS.

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

## 2. Gate 1.1-1 scope

This first slice introduces only infrastructure-free domain vocabulary and invariants under `stage_letter/domain/`.

It MUST NOT:

```text
import SQLAlchemy/FastAPI/Redis/Dramatiq
import experiments/* at runtime
collapse UNKNOWN into OFFLINE
collapse Creator into PlatformAccount
collapse Follow into NotificationPreference
replace event cause with legacy CONFIRMED_* semantics
use session-based delivery idempotency
infer grant exhaustion from SENT
```

## 3. Implemented formal domain package

```text
stage_letter/
  __init__.py
  domain/
    __init__.py
    creators.py
    follows.py
    live.py
    notifications.py
    health.py

tests/
  gate1/
    test_domain_contracts.py
```

The package represents the frozen ten-entity vocabulary:

```text
User
Creator
CreatorProfile
PlatformAccount
Follow
NotificationPreference
LiveObservation
LiveSession
LiveEvent
NotificationDelivery
```

Supporting types include canonical live status, session origin, event type/cause, delivery channel/state, grant state, and runtime health.

## 4. Required Gate 1.1 invariants

Implemented domain contracts preserve:

```text
LiveObservation.status = LIVE | OFFLINE | UNKNOWN
UNKNOWN != OFFLINE
Creator != PlatformAccount
one Creator may own N PlatformAccounts
Follow != NotificationPreference
LiveEvent = event_type + cause
LIVE_STARTED + BOOTSTRAP_LIVE is distinct from LIVE_STARTED + TRANSITION
logical delivery identity = (user_id, live_event_id, channel)
AMBIGUOUS is a first-class delivery state
AMBIGUOUS disallows blind retry
SENT is terminal for one logical delivery only
runtime health = STARTING | HEALTHY | DEGRADED | UNAVAILABLE
admin enabled/disabled is configuration, not runtime health
```

No provider/grant semantics in the pure domain infer global grant exhaustion from `SENT`.

## 5. Formal domain contract tests

`tests/gate1/test_domain_contracts.py` currently covers:

```text
canonical live status exactly three states
UNKNOWN != OFFLINE
Creator / PlatformAccount separation and 1:N capability
Follow / NotificationPreference separation
BOOTSTRAP_LIVE vs TRANSITION distinction
LiveObservation durable identity validation
LiveSession time-range invariant
event-based DeliveryKey identity
AMBIGUOUS no-blind-retry contract
SENT terminal-for-delivery contract
runtime health enum excluding admin DISABLED
```

These are formal Gate 1 tests, not imports of `experiments/*`.

## 6. 1.1-1 acceptance

```text
A. stage_letter/domain package exists                         PASS
B. ten formal entity boundaries represented                  PASS
C. canonical live status is exactly LIVE/OFFLINE/UNKNOWN     PASS
D. delivery identity is event-based                          PASS
E. delivery runtime includes AMBIGUOUS                        PASS
F. no infrastructure imports in domain package               PASS by code boundary review
G. formal domain contract tests added                         PASS
H. local/CI test execution evidence                           PENDING
```

Current decision:

```text
Gate 1.1-1 CODE     PASS
Gate 1.1-1 EVIDENCE PENDING
Gate 1.1-1 overall  CURRENT
```

1.1-1 cannot be marked final PASS until the committed tests are executed successfully in the repository environment.

## 7. Required local acceptance command

From repository root:

```bash
python -m unittest discover -s tests/gate1 -p "test_*.py" -v
```

Expected current suite size: **11 tests**.

Also run an infrastructure-boundary check:

```bash
grep -RniE 'sqlalchemy|fastapi|redis|dramatiq|experiments\.' stage_letter/domain \
  && echo "FAIL: forbidden domain dependency found" \
  || echo "PASS: pure domain has no forbidden runtime dependency"
```

Do not report PASS from expectation alone; record the actual command output.

## 8. Progression rule

After both commands PASS, Gate 1.1-1 closes and Gate 1.1-2 begins: repository/application ports are frozen before any SQLAlchemy model or Alembic migration is implemented.
