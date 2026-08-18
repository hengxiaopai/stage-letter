# Gate 1.1-4 — Alembic EXPAND Migration

Status: **CURRENT / CODE LANDED, EXECUTION EVIDENCE PENDING**

## Purpose

Translate the accepted Gate 1.1 persistence model into one forward-only Alembic revision after the immutable legacy head `e98c1011d830`.

Revision:

```text
a41f6c2e9b77_gate1_expand_formal_domain.py
```

Chain:

```text
5354a9ed7741
  -> c23b5e229894
  -> e98c1011d830
  -> a41f6c2e9b77
```

## EXPAND-only rule

`upgrade()` may add tables, columns, foreign keys, indexes, widen compatible string columns, and deterministically copy existing facts.

It must not:

```text
drop legacy tables/columns
rename legacy tables/columns
rewrite UNKNOWN as OFFLINE
fabricate LiveObservation history
fabricate event cause or event identity
fabricate source_started_at without explicit provenance
fabricate provider/grant truth
```

The migration is forward-only by policy. Corrections require a new revision instead of destructive rollback.

## New formal persistence

The revision creates:

```text
creators
creator_profiles
follows
notification_preferences
live_observations
```

It expands existing formal/legacy-coexistence tables with:

```text
platform_accounts.creator_id
live_sessions.origin
live_sessions.source_started_at
live_events.event_id
live_events.cause
live_events.occurred_at
notification_deliveries.live_event_id
notification_deliveries.next_attempt_at
notification_deliveries.in_flight_at
notification_deliveries.updated_at
```

`notification_deliveries.channel/state` are widened from 16 to 32 characters only so the accepted Gate 0D runtime vocabulary fits.

## Deterministic backfills

Allowed and implemented:

```text
anchors.id -> creators.id
anchors profile fields -> creator_profiles
platform_accounts.anchor_id -> platform_accounts.creator_id
user_subscriptions relationship -> follows
user_subscriptions notification settings -> notification_preferences
live_sessions.started_at -> source_started_at ONLY when started_at_source='platform'
live_events.detected_at -> occurred_at
notification_deliveries.notification_job_id
  -> notification_jobs.live_event_id
  -> notification_deliveries.live_event_id
```

Not backfilled:

```text
live_observations historical rows
live_sessions.origin when unknown
live_events.event_id when no accepted identity exists
live_events.cause when bootstrap/transition cannot be proven
provider/grant state
```

Historical unknowns remain NULL/legacy-unclassified rather than being guessed.

## Constraint hardening boundary

This slice intentionally does not add new hard constraints to legacy-populated tables when those constraints could reject existing data before representative upgrade verification.

Gate 1.1-5 will verify and then harden, including:

```text
one open LiveSession per PlatformAccount using ended_at IS NULL
unique formal LiveEvent event_id when present/new-write policy is active
unique NotificationDelivery(user_id, live_event_id, channel)
canonical LiveObservation status CHECK
required creator/event/delivery fields for new formal writes
```

## Acceptance evidence required

1. Gate 1 test suite including `test_expand_migration_contract.py` passes.
2. `alembic heads` reports only `a41f6c2e9b77`.
3. Offline SQL compilation of the full migration chain succeeds.
4. No DB-connected clean/legacy upgrade claim is made yet; those belong to Gate 1.1-5.

Expected commands from repository root:

```bash
./.venv/Scripts/python.exe -m unittest discover -s tests/gate1 -p "test_*.py" -v
./.venv/Scripts/python.exe -m alembic heads
./.venv/Scripts/python.exe -m alembic upgrade head --sql >/dev/null \
  && echo "PASS: Alembic offline SQL compilation"
```

Gate 1.1-4 remains CURRENT until these execution results are recorded.
