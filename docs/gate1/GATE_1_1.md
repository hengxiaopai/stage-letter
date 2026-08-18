# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PASS / 1.1-2 PASS / 1.1-3 PASS / 1.1-4 PASS / 1.1-5 DB PROBE PASS, STATIC ACCEPTANCE PENDING**

Entry authority: Gate 1.0 PASS.

Detailed freezes/evidence:

- [`GATE_1_1_PORTS_FREEZE.md`](./GATE_1_1_PORTS_FREEZE.md)
- [`GATE_1_1_PERSISTENCE_MODELS.md`](./GATE_1_1_PERSISTENCE_MODELS.md)
- [`GATE_1_1_EXPAND_MIGRATION.md`](./GATE_1_1_EXPAND_MIGRATION.md)
- [`GATE_1_1_DB_VALIDATION.md`](./GATE_1_1_DB_VALIDATION.md)

## 1. Purpose

Gate 1.1 turns the accepted Gate 0 semantics into formal V0.1 domain types,
persistence contracts, SQLAlchemy models, and forward-only PostgreSQL
migrations without inventing historical truth.

Execution order:

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

## 3. Gate 1.1-2 — Repository / Application Ports — PASS

Accepted local evidence:

```text
Ran 17 tests in 0.002s
OK
PASS: domain/application contain no forbidden runtime imports
PASS: no experiments runtime imports
```

Frozen ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
UnitOfWork
```

## 4. Gate 1.1-3 — SQLAlchemy Persistence Models — PASS

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

Formal metadata represents the ten target domain tables and preserves the
accepted event-based delivery identity, durable LiveObservation evidence, and
Creator/PlatformAccount + Follow/NotificationPreference boundaries.

## 5. Gate 1.1-4 — Alembic EXPAND Migration — PASS

Forward-only EXPAND revision:

```text
a41f6c2e9b77_gate1_expand_formal_domain.py
```

Accepted local evidence:

```text
Ran 35 tests in 0.135s
OK

a41f6c2e9b77 (head)

PASS: Alembic offline SQL compilation
```

The first offline SQL attempt failed only because Windows redirected output used
`cp1252` and an immutable historical migration contains Chinese column comments.
Re-running with UTF-8 output succeeded; no migration history was rewritten.

EXPAND preserves legacy tables/columns and performs only deterministic
backfills. It does not fabricate LiveObservation history, source start time,
event identity/cause, session origin, provider truth, or UNKNOWN->OFFLINE.

Gate 1.1-4: **PASS**.

## 6. Gate 1.1-5 — DB Constraint Hardening + Clean/Legacy Validation — CURRENT

Hardening revision:

```text
b63e4f9a1c20_gate1_harden_constraints.py
```

Current revision chain:

```text
5354a9ed7741
  -> c23b5e229894
  -> e98c1011d830
  -> a41f6c2e9b77
  -> b63e4f9a1c20
```

Hardening adds only deterministic constraints, including canonical observation
status, formal open-session uniqueness, event-based delivery identity, and
non-null deterministic bridge facts. Unknown legacy event id/cause/session
origin remain unknown/null.

Real PostgreSQL probe:

```text
scripts/gate1_db_migration_probe.py
```

Accepted user-local DB evidence on 2026-08-19:

```text
[clean] PASS -> b63e4f9a1c20
[legacy] PASS -> b63e4f9a1c20
PASS: Gate 1.1-5 clean + legacy PostgreSQL migration probe
[cleanup] dropped stageletter_gate11_clean
[cleanup] dropped stageletter_gate11_legacy
```

The probe proves:

```text
clean database migration                                     PASS
representative legacy migration                             PASS
deterministic backfills                                     PASS
no fabricated LiveObservation/event cause/session origin    PASS
invalid canonical observation status rejected               PASS
second ended_at=NULL session rejected                       PASS
duplicate user/event/channel delivery rejected              PASS
temporary DB cleanup                                        PASS
```

Gate 1.1-5 is not closed yet because the hardening revision still needs explicit
local evidence for:

```text
full Gate 1 contract suite
alembic heads == b63e4f9a1c20
offline SQL compilation through b63e4f9a1c20
```

## 7. Remaining Gate 1.1 plan

After 1.1-5 PASS:

```text
1.1-6 Gate 0 regression and golden-path comparison
```

No legacy table/column is dropped in Gate 1.1.

## 8. Stop rules

Gate 1.1 must stop with FAIL/BLOCKED if any implementation requires:

```text
UNKNOWN -> OFFLINE
fabricated LiveObservation history
fabricated source_started_at
invented BOOTSTRAP vs TRANSITION cause
invented historical event identity
session-based delivery idempotency
blind resend from AMBIGUOUS
SENT -> global grant exhaustion inference
provider/notification failure -> creator live truth mutation
silent resolution of conflicting legacy rows
```

## 9. Current progression

```text
Gate 1.0    PASS
Gate 1.1-1  PASS / pure domain + 11/11
Gate 1.1-2  PASS / ports + 17/17 + AST dependency audit
Gate 1.1-3  PASS / SQLAlchemy models + 25/25 + metadata 10/10
Gate 1.1-4  PASS / EXPAND + 35/35 + head + UTF-8 offline SQL
Gate 1.1-5  CURRENT / real DB clean+legacy PASS; static acceptance pending
Gate 1.1-6  NOT STARTED
Gate 1.1    CURRENT
```
