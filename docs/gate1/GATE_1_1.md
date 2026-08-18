# Gate 1.1 — Domain Model + PostgreSQL Schema

Status: **CURRENT / 1.1-1 PASS / 1.1-2 PASS / 1.1-3 PASS / 1.1-4 PASS / 1.1-5 PASS / 1.1-6 CURRENT**

Entry authority: Gate 1.0 PASS.

Detailed freezes/evidence:

- [`GATE_1_1_PORTS_FREEZE.md`](./GATE_1_1_PORTS_FREEZE.md)
- [`GATE_1_1_PERSISTENCE_MODELS.md`](./GATE_1_1_PERSISTENCE_MODELS.md)
- [`GATE_1_1_EXPAND_MIGRATION.md`](./GATE_1_1_EXPAND_MIGRATION.md)
- [`GATE_1_1_DB_VALIDATION.md`](./GATE_1_1_DB_VALIDATION.md)
- [`GATE_1_1_REGRESSION.md`](./GATE_1_1_REGRESSION.md)

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

Accepted evidence:

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

Accepted evidence:

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

Accepted environment/evidence:

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

## 6. Gate 1.1-5 — DB Constraint Hardening + Clean/Legacy Validation — PASS

Hardening revision:

```text
b63e4f9a1c20_gate1_harden_constraints.py
```

Revision chain:

```text
5354a9ed7741
  -> c23b5e229894
  -> e98c1011d830
  -> a41f6c2e9b77
  -> b63e4f9a1c20
```

Accepted real PostgreSQL evidence on 2026-08-19:

```text
[clean] PASS -> b63e4f9a1c20
[legacy] PASS -> b63e4f9a1c20
PASS: Gate 1.1-5 clean + legacy PostgreSQL migration probe
[cleanup] dropped stageletter_gate11_clean
[cleanup] dropped stageletter_gate11_legacy
```

The probe proved deterministic backfills, no fabricated historical
LiveObservation/event cause/session origin, hard rejection of invalid canonical
status, duplicate open sessions, and duplicate logical deliveries. The operator
subsequently confirmed the remaining static acceptance checks passed:

```text
full Gate 1 contract suite                     PASS
alembic heads == b63e4f9a1c20                 PASS
offline SQL compilation through hardening     PASS
```

Gate 1.1-5: **PASS**.

## 7. Gate 1.1-6 — Gate 0 Regression + Golden Path Comparison — CURRENT

Regression assets have landed:

```text
tests/gate1/test_gate0_regression_contract.py
scripts/gate1_regression_probe.py
docs/gate1/GATE_1_1_REGRESSION.md
```

The formal parity tests compare accepted Gate 0 oracle vocabulary against Gate 1:

```text
ObservationStatus / CanonicalStatus -> LiveStatus
SessionOrigin                        -> SessionOrigin
LiveEventType / Cause                -> formal event type/cause
Channel                              -> DeliveryChannel
GrantState                           -> GrantState
ExecutionState                       -> DeliveryState
HealthState                          -> RuntimeHealthState
```

They also prove `stage_letter/*` does not import `experiments/*` at runtime.

The regression probe runs accepted deterministic suites:

```text
Gate 0B >= 37 tests
Gate 0C >= 65 tests
Gate 0D >= 54 tests
Gate 0E >= 15 tests
Gate 1  >= 55 tests
```

This is a regression/oracle comparison only. It does not claim the later formal
state/source/notification runtime integrations are already implemented, and it
does not repeat real WeChat/provider sends.

Gate 0A remains DEGRADED with its known deferred lifecycle evidence gap.

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
Gate 1.1-5  PASS / hardening + clean/legacy PostgreSQL validation
Gate 1.1-6  CURRENT / regression harness landed; local evidence pending
Gate 1.1    CURRENT
```

Gate 1.1 may close only after Gate 1.1-6 regression evidence passes.
