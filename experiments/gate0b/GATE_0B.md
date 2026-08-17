# Gate 0B — State Engine + LiveSession

Status: **IN PROGRESS**

## Scope

Gate 0B validates the domain behavior between normalized observations and canonical live-session state:

```text
LiveObservation
    -> State Engine
    -> LiveSession
    -> LiveEvent
```

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

## Gate 0B-1 — Pure state model — PASS

State chain:

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

Default Gate configuration:

```text
live_confirmations_required    = 2
offline_confirmations_required = 2
```

`UNKNOWN` is a pause/no-op observation: it does not advance or cancel pending transitions, never opens/closes a session, and never emits LIVE_STARTED/LIVE_ENDED.

Explicit opposite evidence cancels pending transitions:

```text
LIVE_PENDING + OFFLINE -> OFFLINE_CONFIRMED
OFFLINE_PENDING + LIVE -> LIVE_CONFIRMED
```

### Bootstrap rule — unresolved for production

Gate 0B-1/0B-2 preserve the conservative bootstrap chain:

```text
UNKNOWN + LIVE -> UNKNOWN
```

A new account therefore requires an explicit OFFLINE baseline before a later LIVE transition can become canonical. This avoids fabricating a start event but means an account first onboarded while already LIVE is not represented correctly. Gate 0B-3 must resolve this explicitly.

### Gate 0B-1 acceptance — PASS

The pure-domain suite proves UNKNOWN safety, explicit OFFLINE baseline, LIVE/OFFLINE pending confirmation, opposite-state cancellation, duplicate observation idempotency, no duplicate sessions/events, distinct session cycles, and config validation.

Initial CI evidence:

```text
workflow  Gate 0B State Smoke
run       32005422864
result    completed / success
head      ac6f07e6302b6c1ebdaafc6ad64dce8314771489
```

The engine also exposes an explicit `EngineSnapshot` / `StateEngine.from_snapshot()` boundary so persistence can reconstruct behavior-relevant state without defining domain semantics itself.

## Gate 0B-2 — SQLite persistence + restart safety — PASS

SQLite is used only as a minimal standard-library transaction harness. It is **not** a production database selection.

Persistent projection:

```text
engine_state
observations
sessions
events
```

Every observation is handled in one transaction:

```text
BEGIN IMMEDIATE
  load durable EngineSnapshot
  process canonical LiveObservation
  persist observation idempotency key
  persist engine state + pending counters
  persist LiveSession projection
  persist LiveEvent projection
COMMIT
```

Any exception before COMMIT rolls the full unit back.

Durable constraints include:

```text
observations PK(account_id, observation_id)
sessions     PK(account_id, session_id)
events       PK(account_id, event_type, session_id)
one open session per account_id via partial UNIQUE index
event -> session foreign key
```

### Gate 0B-2 persistence acceptance — PASS 12/12

```text
01 OFFLINE baseline survives restart                         PASS
02 LIVE_PENDING + streak survives restart and confirms       PASS
03 open LiveSession survives restart                         PASS
04 OFFLINE_PENDING survives restart and closes same session  PASS
05 duplicate observation survives restart without new event  PASS
06 UNKNOWN after restart never closes open session           PASS
07 session id sequence continues across restart              PASS
08 failure after observation insert rolls back atomically    PASS
09 state/session/event transition rollback                   PASS
10 persisted EngineConfig reused; mismatch rejected          PASS
11 fail after session row / before event -> full rollback     PASS
12 two PlatformAccounts isolated in one SQLite database      PASS
```

The strongest fault injection deliberately interrupts a second LIVE confirmation **after the session row has been written but before the LIVE_STARTED event is written**. After rollback and restart the database still contains the prior `LIVE_PENDING` state with zero session and zero event; retry creates exactly one session and one event.

### Latest Gate 0B-2 CI evidence — PASS

```text
workflow  Gate 0B Persistence Smoke
run       32005925909
head      2cc6430829fec8b3e5d96afe6e5c30f17217101c
result    completed / success

workflow  Gate 0B State Smoke
run       32005925822
head      2cc6430829fec8b3e5d96afe6e5c30f17217101c
result    completed / success

Python    3.13.15
suite     26 tests total / 26 PASS
```

Gate 0B-2 therefore proves restart-safe idempotency, pending-state durability, open-session durability, transaction rollback safety, and account isolation with no external runtime dependency.

## Current domain objects

### LiveObservation

```text
observation_id
status: LIVE | OFFLINE | UNKNOWN
observed_at
source
```

`observation_id` is the durable idempotency key.

### LiveSession

```text
session_id
opened_at
closed_at | null
```

Exactly one session may be open at a time per engine / PlatformAccount.

### LiveEvent

```text
LIVE_STARTED
LIVE_ENDED
```

Both events are bound to the same session_id for one normal observed lifecycle.

## Next: Gate 0B-3 — bootstrap + observation ordering policy

Two production-significant semantics remain unresolved.

### A. Account first observed while already LIVE

Current behavior:

```text
new account + LIVE -> UNKNOWN
```

This is safe against false notifications but incomplete for Stage Letter: a user may follow a creator who is already live.

Recommended domain direction for Gate 0B-3:

```text
repeated confirmed initial LIVE
  -> canonical open LiveSession
  -> session origin explicitly marks BOOTSTRAP / DISCOVERED_LIVE
  -> must NOT be indistinguishable from a real OFFLINE -> LIVE start event
```

Gate 0B-3 must freeze how this affects LiveEvent semantics, later notification eligibility, `opened_at` when source start time is unavailable, UNKNOWN during bootstrap, restart behavior, and idempotency.

### B. Out-of-order / stale observations

Unique observation ids do not prevent a slower old request from arriving after a newer result. A stale OFFLINE result must never regress a newer LIVE state.

Gate 0B-3 must define a durable per-account ordering watermark and prove:

```text
newer observation accepted
older unique observation rejected as STALE / no state mutation
stale observation cannot open or close a session
stale observation cannot advance pending confirmation counters
ordering watermark survives restart
UNKNOWN and decisive observations obey one explicit ordering rule
```

No provider HTTP logic or notification delivery implementation belongs in 0B-3; only the canonical domain facts and ordering rules are in scope.

## Local verification

```bash
python -m unittest discover -s experiments/gate0b -p "test_*.py" -v
```

Gate 0B-1/0B-2 use only the Python standard library.

## Current progression

```text
Gate 0A evidence status      DEGRADED / deferred lifecycle gap
Gate 0A progression          ALLOWED WITH KNOWN GAP
Gate 0B-1                    PASS
Gate 0B-2                    PASS
Gate 0B-3                    NEXT
Gate 0B overall              IN PROGRESS
Gate 0C                      NOT STARTED
```
