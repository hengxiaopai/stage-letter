# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PURE DOMAIN STARTED**

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

## 3. Frozen domain vocabulary

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

Supporting domain enums/types include runtime health and delivery runtime states.

## 4. Required Gate 1.1 invariants

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
SENT is terminal for one logical delivery only
runtime health = STARTING | HEALTHY | DEGRADED | UNAVAILABLE
admin enabled/disabled is configuration, not runtime health
```

## 5. 1.1-1 acceptance

```text
A. stage_letter/domain package exists                         CURRENT
B. ten formal entity boundaries represented                  CURRENT
C. canonical live status is exactly LIVE/OFFLINE/UNKNOWN     CURRENT
D. delivery identity is event-based                          CURRENT
E. delivery runtime includes AMBIGUOUS                        CURRENT
F. no infrastructure imports in domain package               CURRENT
G. formal domain contract tests added                         CURRENT
H. local/CI test evidence                                     PENDING
```

1.1-1 cannot be marked PASS until test execution evidence is supplied.

## 6. Progression rule

After 1.1-1 code is reviewed and tests pass, Gate 1.1-2 will freeze repository/application ports before any SQLAlchemy model or migration is written.
