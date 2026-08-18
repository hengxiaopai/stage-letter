# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PASS / 1.1-2 PASS / 1.1-3 PASS / 1.1-4 EXPAND CURRENT**

Entry authority: Gate 1.0 PASS.

Detailed freezes/evidence:

- [`GATE_1_1_PORTS_FREEZE.md`](./GATE_1_1_PORTS_FREEZE.md)
- [`GATE_1_1_PERSISTENCE_MODELS.md`](./GATE_1_1_PERSISTENCE_MODELS.md)
- [`GATE_1_1_EXPAND_MIGRATION.md`](./GATE_1_1_EXPAND_MIGRATION.md)

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

Accepted local evidence:

```text
Ran 11 tests in 0.002s
OK
PASS: pure domain has no forbidden runtime dependency
```

Frozen invariants include:

```text
LiveObservation.status = LIVE | OFFLINE | UNKNOWN
UNKNOWN != OFFLINE
Creator != PlatformAccount
Follow != NotificationPreference
LIVE_STARTED + BOOTSTRAP_LIVE != LIVE_STARTED + TRANSITION
logical NotificationDelivery identity = (user_id, live_event_id, channel)
AMBIGUOUS forbids blind retry
runtime health != admin disabled
```

Gate 1.1-1: **PASS**.

## 3. Gate 1.1-2 — Repository / Application Ports — PASS

Frozen ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
UnitOfWork
```

Accepted local evidence:

```text
Ran 17 tests in 0.002s
OK
PASS: domain/application contain no forbidden runtime imports
PASS: no experiments runtime imports
```

Gate 1.1-2: **PASS**.

## 4. Gate 1.1-3 — SQLAlchemy Persistence Models — PASS

Formal metadata represents exactly the ten target domain tables:

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

Accepted user-local environment/evidence:

```text
Python      3.13.14
SQLAlchemy  2.0.52
Alembic     1.19.1
PASS: Gate 1 DB dependencies available

Ran 25 tests in 0.004s
OK

count: 10
PASS: formal persistence metadata loaded
```

Persistence contracts include:

```text
PlatformAccount -> creator_id owner
Follow -> unique(user_id, platform_account_id)
NotificationPreference -> separate persistence
LiveObservation -> source-scoped stable durable identity
LiveSession -> target partial unique open-session invariant
LiveEvent -> event_id + event_type + cause + occurred_at
NotificationDelivery -> event-based identity + durable send runtime fields
```

Gate 1.1-3: **PASS**.

## 5. Gate 1.1-4 — Alembic EXPAND Migration — CURRENT

Forward-only revision landed:

```text
a41f6c2e9b77_gate1_expand_formal_domain.py
```

Revision chain:

```text
5354a9ed7741
  -> c23b5e229894
  -> e98c1011d830
  -> a41f6c2e9b77
```

The upgrade is additive and keeps all legacy data/tables/columns. It creates the new formal tables and adds bridge columns needed by the post-EXPAND model.

Deterministic backfills only:

```text
anchors -> creators / creator_profiles
platform_accounts.anchor_id -> creator_id
user_subscriptions -> follows
user_subscriptions notification settings -> notification_preferences
live_sessions.started_at -> source_started_at only when started_at_source='platform'
live_events.detected_at -> occurred_at
notification_deliveries.notification_job_id -> notification_jobs.live_event_id -> delivery.live_event_id
```

Explicitly not fabricated:

```text
historical LiveObservation rows
unknown LiveSession origin
unknown LiveEvent event_id/cause
provider/grant truth
UNKNOWN -> OFFLINE
```

Contract tests have landed in:

```text
tests/gate1/test_expand_migration_contract.py
```

1.1-4 remains CURRENT until local evidence confirms:

```text
full Gate 1 suite passes
alembic heads == a41f6c2e9b77
offline SQL compilation succeeds
```

DB-connected clean/legacy upgrade validation is deferred to Gate 1.1-5 by design.

## 6. Remaining Gate 1.1 plan

After 1.1-4 PASS:

```text
1.1-5 DB constraint hardening + clean/legacy migration tests
1.1-6 Gate 0 regression and golden-path comparison
```

No legacy table/column is dropped in Gate 1.1.

## 7. Stop rules

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

## 8. Current progression

```text
Gate 1.0    PASS
Gate 1.1-1  PASS / pure domain + 11/11
Gate 1.1-2  PASS / ports + 17/17 + AST dependency audit
Gate 1.1-3  PASS / SQLAlchemy models + 25/25 + metadata 10/10
Gate 1.1-4  CURRENT / EXPAND migration landed; execution evidence pending
Gate 1.1-5  NOT STARTED
Gate 1.1    CURRENT
```
