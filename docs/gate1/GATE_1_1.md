# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PASS / 1.1-2 PASS / 1.1-3 PERSISTENCE MODELS STARTED**

Entry authority: Gate 1.0 PASS.

Detailed freezes:

- [`GATE_1_1_PORTS_FREEZE.md`](./GATE_1_1_PORTS_FREEZE.md)
- [`GATE_1_1_PERSISTENCE_MODELS.md`](./GATE_1_1_PERSISTENCE_MODELS.md)

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

Local evidence on 2026-08-18:

```text
Ran 11 tests in 0.002s
OK
PASS: pure domain has no forbidden runtime dependency
```

Gate 1.1-1: **PASS**.

## 3. Gate 1.1-2 — Repository / Application Ports — PASS

Formal application ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
UnitOfWork
```

Accepted local evidence on 2026-08-18:

```text
python -m unittest discover -s tests/gate1 -p "test_*.py" -v
Ran 17 tests in 0.002s
OK
```

The initial text grep dependency check was rejected as a false positive because it matched explanatory docstring text and `__pycache__`. A Python AST import audit then returned:

```text
PASS: domain/application contain no forbidden runtime imports
```

Separate runtime-boundary evidence:

```text
PASS: no experiments runtime imports
```

Acceptance:

```text
repository ports are Protocol contracts                    PASS
repository I/O is async                                   PASS
LiveObservation has first-class persistence methods       PASS
Follow / NotificationPreference remain separate          PASS
delivery persistence is keyed by DeliveryKey             PASS
UnitOfWork commit/rollback boundary exists                PASS
17/17 Gate 1 tests pass                                   PASS
AST forbidden-import audit                                PASS
```

Gate 1.1-2: **PASS**.

## 4. Gate 1.1-3 — SQLAlchemy Persistence Models — CURRENT

Formal infrastructure package has started:

```text
stage_letter/infrastructure/
  db/
    base.py
    models.py
```

The SQLAlchemy metadata represents exactly the ten frozen target domain tables:

```text
users
creators
creator_profiles
platform_accounts
follows
notification_preferences
live_observations
live_sessions
live_events
notification_deliveries
```

Persistence contracts include:

```text
PlatformAccount -> creator_id owner
Follow -> unique(user_id, platform_account_id)
NotificationPreference -> separate persistence
LiveObservation -> durable table with source-scoped stable identity
LiveSession -> PostgreSQL partial unique open-session index
LiveEvent -> event_id + event_type + cause + occurred_at
NotificationDelivery -> unique(user_id, live_event_id, channel)
NotificationDelivery -> IN_FLIGHT/retry persistence fields
```

Legacy required columns that must coexist during EXPAND are explicitly exposed only as `legacy_*` infrastructure bridge fields. They are not formal domain truth.

Contract tests:

```text
tests/gate1/test_persistence_models.py
```

1.1-3 cannot be marked PASS until local test execution confirms the new SQLAlchemy metadata contracts and the existing 1.1-1/1.1-2 tests remain green.

## 5. Remaining Gate 1.1 plan

After 1.1-3 PASS:

```text
1.1-4 Alembic EXPAND migration + deterministic backfill rules
1.1-5 DB constraints + clean/legacy migration tests
1.1-6 Gate 0 regression and golden-path comparison
```

No legacy table/column is dropped in Gate 1.1.

## 6. Stop rules

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

## 7. Current progression

```text
Gate 1.0    PASS
Gate 1.1-1  PASS / pure domain + 11/11 evidence
Gate 1.1-2  PASS / ports + 17/17 + AST dependency audit
Gate 1.1-3  CURRENT / SQLAlchemy models landed; evidence pending
Gate 1.1-4  NOT STARTED
Gate 1.1    CURRENT
```
