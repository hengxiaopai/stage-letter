# Gate 1.1-5 — PostgreSQL Constraint Hardening + Clean/Legacy Validation

Status: **CURRENT / REAL DB PROBE PASS / STATIC ACCEPTANCE PENDING**

## Purpose

Gate 1.1-5 is the first database-connected acceptance slice. It proves that the
forward-only Gate 1 schema can be applied both to a clean PostgreSQL database
and to a representative pre-Gate-1 database without inventing historical truth.

The repository development PostgreSQL service is defined by `docker-compose.yml`
as PostgreSQL 16 on host port 5433. The probe creates isolated temporary
databases and never modifies the normal `stageletter` database.

## Hardening revision

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

Safe hardening performed:

```text
platform_accounts.creator_id -> NOT NULL after deterministic anchor mapping
live_observations.status -> CHECK LIVE/OFFLINE/UNKNOWN
live_sessions.origin -> NULL or TRANSITION/BOOTSTRAP_LIVE
live_sessions -> one ended_at IS NULL row per platform account
live_events.occurred_at -> NOT NULL after detected_at backfill
live_events.event_id -> unique when present; legacy NULL preserved
live_events.cause -> NULL or TRANSITION/BOOTSTRAP_LIVE
notification_deliveries.live_event_id -> NOT NULL after job->event backfill
legacy channel 'wechat' -> deterministic WECHAT_SUBSCRIBE normalization
notification delivery identity -> unique(user_id, live_event_id, channel)
notification_deliveries.updated_at -> deterministic non-null bookkeeping
```

Not hardened by guessing:

```text
legacy event_id remains NULL if never persisted
legacy event cause remains NULL if never persisted
legacy session origin remains NULL if never persisted
legacy FAILED delivery state is not reclassified
historical LiveObservation rows are not synthesized
source_started_at is not invented
```

If real legacy data violates a newly required invariant (for example multiple
`ended_at IS NULL` sessions for one account), migration must stop and expose the
conflict. It must not silently choose a row or fabricate an end time.

## Real PostgreSQL probe

`scripts/gate1_db_migration_probe.py` performs two isolated scenarios:

### CLEAN

```text
empty temporary database
-> alembic upgrade head
-> verify current revision
-> verify ten formal tables
-> verify hardening constraints/indexes
```

### LEGACY

```text
empty temporary database
-> alembic upgrade e98c1011d830
-> seed representative persisted legacy facts
-> alembic upgrade head
-> verify deterministic backfills
-> verify no LiveObservation fabrication
-> verify event identity/cause remain unknown
-> verify platform-proven source_started_at only
-> verify legacy WeChat channel normalization
-> prove invalid observation status is rejected
-> prove second ended_at=NULL session is rejected
-> prove duplicate user/event/channel delivery is rejected
```

The probe drops both temporary databases in `finally`.

## Accepted real DB evidence — 2026-08-19

User-local execution completed successfully:

```text
[clean] database created
...
[clean] PASS -> b63e4f9a1c20

[legacy] database created
...
[legacy] representative fixture seeded
...
[legacy] PASS -> b63e4f9a1c20

PASS: Gate 1.1-5 clean + legacy PostgreSQL migration probe
[cleanup] dropped stageletter_gate11_clean
[cleanup] dropped stageletter_gate11_legacy
```

This proves the database-connected portion of Gate 1.1-5:

```text
clean database -> current head                              PASS
representative legacy database -> current head             PASS
deterministic creator/follow/preference/delivery backfill  PASS
historical LiveObservation fabrication absent              PASS
unknown legacy event id/cause/session origin preserved     PASS
platform-proven source_started_at behavior                 PASS
invalid canonical observation status rejected              PASS
second ended_at=NULL session rejected                       PASS
duplicate user/event/channel delivery rejected             PASS
temporary database cleanup                                 PASS
```

## Acceptance

Gate 1.1-5 PASS requires all of:

```text
A. full Gate 1 contract suite passes                         PENDING
B. alembic heads == b63e4f9a1c20                           PENDING
C. offline SQL compilation through hardening revision       PENDING
D. PostgreSQL service operational/reachable                 PASS
E. clean database -> head                                   PASS
F. representative legacy database -> head                   PASS
G. deterministic backfills verified                         PASS
H. no historical truth invented                             PASS
I. hard DB constraints proven by rejected invalid writes    PASS
J. temporary DB cleanup confirmed                           PASS
```

The successful probe establishes D-J. A-C still require explicit local evidence
for the hardening revision before Gate 1.1-5 may be closed.

No production/normal development database is modified by the acceptance probe.

## Stop rules

FAIL/BLOCKED instead of guessing if any migration requires:

```text
UNKNOWN -> OFFLINE
fabricated observation history
fabricated source_started_at
invented event cause/id
invented session origin
blind notification retry semantics
provider/grant inference
silent resolution of duplicate open sessions or deliveries
```

After Gate 1.1-5 PASS, Gate 1.1-6 performs Gate 0 regression/golden-path
comparison against the formal Gate 1 boundaries.
