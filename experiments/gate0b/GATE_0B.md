# Gate 0B — State Engine + LiveSession

Status: **IN PROGRESS**

## Scope

Gate 0B validates the pure domain behavior between normalized observations and canonical live-session state:

```text
LiveObservation
    -> State Engine
    -> LiveSession
    -> LiveEvent
```

This Gate deliberately excludes provider HTTP logic, database persistence, Redis, queues, WeChat notification delivery, frontend UI, and production deployment.

Gate 0A progression was allowed with a known deferred lifecycle evidence gap. Gate 0B must not convert that waiver into fabricated evidence.

## Frozen safety invariants

```text
UNKNOWN != OFFLINE
UNKNOWN never closes a LiveSession
one PlatformAccount -> at most one open LiveSession
one confirmed session -> exactly one LIVE_STARTED
one closed session -> exactly one LIVE_ENDED
duplicate observation -> no duplicate transition/session/event
stale title/live_url metadata cannot override explicit state
```

## Gate 0B-1 state model

```text
UNKNOWN
   |
   | explicit OFFLINE baseline
   v
OFFLINE_CONFIRMED
   |
   | LIVE #1
   v
LIVE_PENDING
   |
   | LIVE confirmations reach threshold
   v
LIVE_CONFIRMED
   |
   | OFFLINE #1
   v
OFFLINE_PENDING
   |
   | OFFLINE confirmations reach threshold
   v
OFFLINE_CONFIRMED
```

Default Gate test configuration:

```text
live_confirmations_required    = 2
offline_confirmations_required = 2
```

Thresholds are configuration, not hard-coded product truth.

### UNKNOWN behavior

`UNKNOWN` is a pause/no-op observation:

- does not advance a pending transition;
- does not cancel a pending transition;
- never opens a session;
- never closes a session;
- never emits LIVE_STARTED or LIVE_ENDED.

An explicit opposite decisive observation cancels the corresponding pending transition:

```text
LIVE_PENDING + OFFLINE -> OFFLINE_CONFIRMED
OFFLINE_PENDING + LIVE -> LIVE_CONFIRMED
```

## Bootstrap rule — explicit known limitation

Gate 0B-1 preserves the previously frozen bootstrap chain: a new engine starts `UNKNOWN` and requires an explicit `OFFLINE` baseline before it can confirm a later LIVE transition.

Therefore:

```text
UNKNOWN + LIVE -> UNKNOWN
```

This is intentionally conservative but means an account first onboarded while already LIVE will not create a canonical LiveSession until an OFFLINE baseline has been observed. This policy is **not** silently changed in Gate 0B-1. It must be revisited explicitly in a later Gate 0B step before production architecture is frozen.

## Domain objects

### LiveObservation

Required Gate fields:

```text
observation_id
status: LIVE | OFFLINE | UNKNOWN
observed_at
source
```

`observation_id` is the idempotency key for the Gate engine.

### LiveSession

Gate fields:

```text
session_id
opened_at
closed_at | null
```

Exactly one session may be open at a time for one engine / PlatformAccount.

### LiveEvent

Gate types:

```text
LIVE_STARTED
LIVE_ENDED
```

Both events are bound to the same `session_id` for one lifecycle.

## Gate 0B-1 acceptance matrix

The standard-library unittest suite must prove all of the following:

```text
01 UNKNOWN does not become OFFLINE                         PASS required
02 initial LIVE cannot bypass frozen OFFLINE baseline     PASS required
03 explicit OFFLINE creates OFFLINE_CONFIRMED baseline    PASS required
04 first LIVE creates LIVE_PENDING only                   PASS required
05 second LIVE confirms and opens exactly one session     PASS required
06 opposite OFFLINE cancels LIVE_PENDING                  PASS required
07 UNKNOWN pauses LIVE_PENDING                            PASS required
08 repeated LIVE does not duplicate session/event         PASS required
09 first OFFLINE creates OFFLINE_PENDING only             PASS required
10 second OFFLINE closes the same session                 PASS required
11 UNKNOWN during OFFLINE_PENDING never closes session    PASS required
12 LIVE cancels OFFLINE_PENDING                           PASS required
13 repeated OFFLINE does not duplicate LIVE_ENDED         PASS required
14 duplicate observation_id is idempotent                 PASS required
15 two full cycles create two distinct sessions           PASS required
16 invalid confirmation threshold is rejected             PASS required
```

## PASS rule

Gate 0B-1 is PASS only when:

```text
syntax check                         PASS
all unittest acceptance cases        PASS
GitHub Actions Gate 0B State Smoke   PASS
no external runtime dependency       PASS
```

A test implementation passing does not yet mean Gate 0B is complete. Later Gate 0B work must add persistence/transaction semantics and explicitly decide the initial-LIVE bootstrap policy.

## Local command

From repository root:

```bash
python -m unittest discover -s experiments/gate0b -p "test_*.py" -v
```

On the current Windows Gate virtualenv, the equivalent command can be run with any installed Python 3.12+ interpreter; the Gate 0B-1 implementation uses only the standard library.

## Current progression

```text
Gate 0A evidence status      DEGRADED / deferred lifecycle gap
Gate 0A progression          ALLOWED WITH KNOWN GAP
Gate 0B-1                    IMPLEMENTED / AWAITING TEST EVIDENCE
Gate 0B overall              IN PROGRESS
Gate 0C                      NOT STARTED
```
