# Gate 1.1-5 — PostgreSQL Constraint Hardening + Clean/Legacy Validation

Status: **PASS**

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

If real legacy data violates a newly required invariant, migration stops and
exposes the conflict. It does not silently choose a row or fabricate history.

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
[clean] PASS -> b63e4f9a1c20
[legacy] PASS -> b63e4f9a1c20
PASS: Gate 1.1-5 clean + legacy PostgreSQL migration probe
[cleanup] dropped stageletter_gate11_clean
[cleanup] dropped stageletter_gate11_legacy
```

The operator subsequently confirmed the remaining static acceptance checks also
passed for the hardening revision.

## Acceptance

```text
A. full Gate 1 contract suite passes                         PASS / operator confirmed
B. alembic heads == b63e4f9a1c20                           PASS / operator confirmed
C. offline SQL compilation through hardening revision       PASS / operator confirmed
D. PostgreSQL service operational/reachable                 PASS
E. clean database -> head                                   PASS
F. representative legacy database -> head                   PASS
G. deterministic backfills verified                         PASS
H. no historical truth invented                             PASS
I. hard DB constraints proven by rejected invalid writes    PASS
J. temporary DB cleanup confirmed                           PASS
```

Gate 1.1-5: **PASS**.

No production/normal development database was modified by the acceptance probe.

## Preserved stop rules

The accepted migration path does not require:

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

Next: Gate 1.1-6 performs Gate 0 deterministic regression/golden-path comparison
against the formal Gate 1 boundaries.
