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

Default Gate test configuration:

```text
live_confirmations_required    = 2
offline_confirmations_required = 2
```

Thresholds are configuration, not hard-coded product truth.

`UNKNOWN` is a pause/no-op observation: it does not advance or cancel pending transitions, never opens/closes a session, and never emits LIVE_STARTED/LIVE_ENDED.

Explicit opposite evidence cancels pending transitions:

```text
LIVE_PENDING + OFFLINE -> OFFLINE_CONFIRMED
OFFLINE_PENDING + LIVE -> LIVE_CONFIRMED
```

### Bootstrap rule — still unresolved for production

Gate 0B-1 preserves the conservative bootstrap chain:

```text
UNKNOWN + LIVE -> UNKNOWN
```

A new account therefore requires an explicit OFFLINE baseline before a later LIVE transition can become canonical. This avoids false startup events, but it also means an account first onboarded while already LIVE is not represented correctly. Gate 0B-3 must decide this explicitly rather than changing it silently.

### Gate 0B-1 acceptance matrix — PASS

```text
01 UNKNOWN does not become OFFLINE                         PASS
02 initial LIVE cannot bypass frozen OFFLINE baseline     PASS
03 explicit OFFLINE creates OFFLINE_CONFIRMED baseline    PASS
04 first LIVE creates LIVE_PENDING only                   PASS
05 second LIVE confirms and opens exactly one session     PASS
06 opposite OFFLINE cancels LIVE_PENDING                  PASS
07 UNKNOWN pauses LIVE_PENDING                            PASS
08 repeated LIVE does not duplicate session/event         PASS
09 first OFFLINE creates OFFLINE_PENDING only             PASS
10 second OFFLINE closes the same session                 PASS
11 UNKNOWN during OFFLINE_PENDING never closes session    PASS
12 LIVE cancels OFFLINE_PENDING                           PASS
13 repeated OFFLINE does not duplicate LIVE_ENDED         PASS
14 duplicate observation_id is idempotent                 PASS
15 two full cycles create two distinct sessions           PASS
16 invalid confirmation threshold is rejected             PASS
```

GitHub Actions evidence:

```text
workflow  Gate 0B State Smoke
run       32005422864
result    completed / success
head      ac6f07e6302b6c1ebdaafc6ad64dce8314771489
```

A domain `EngineSnapshot` / `StateEngine.from_snapshot()` boundary was also added so behavior-relevant engine state can be reconstructed without coupling the state machine to one database implementation. Its State Smoke run also completed successfully:

```text
run       32005728580
result    completed / success
head      e144a51ed843fd80f7ec46fb90b7e582bf1a21c1
```

## Gate 0B-2 — SQLite persistence + restart safety — PASS

Gate 0B-2 deliberately uses only Python standard-library `sqlite3`. SQLite is an experimental persistence harness here, not a production database decision.

Persistent model:

```text
engine_state
observations
sessions
events
```

Every new observation is handled in one SQLite transaction:

```text
BEGIN IMMEDIATE
  load durable state
  check durable observation idempotency
  process through canonical StateEngine
  insert observation
  write engine state + sessions + events
COMMIT
```

Any exception rolls back the full unit. The next process/restart loads the last committed state.

### Gate 0B-2 acceptance matrix — PASS 10/10

```text
01 OFFLINE baseline survives restart                         PASS
02 LIVE_PENDING + streak survives restart and confirms       PASS
03 open LiveSession survives restart                         PASS
04 OFFLINE_PENDING survives restart and closes same session  PASS
05 duplicate observation survives restart without new event  PASS
06 UNKNOWN after restart never closes open session           PASS
07 session id sequence continues across restart              PASS
08 failure after observation insert rolls back atomically    PASS
09 failure after session/event state write rolls back        PASS
10 persisted EngineConfig is reused; mismatch rejected       PASS
```

The transaction fault tests deliberately inject failures at two boundaries. After rollback, retrying the same observation remains valid and produces exactly one canonical transition.

### Gate 0B-2 CI evidence — PASS

```text
workflow  Gate 0B Persistence Smoke
run       32005733826
head      84be212b33cdd1b707cbed832013c4a6e1f53d78
result    completed / success
Python    3.13.15
suite     24 tests total / OK
```

The 24-test CI run contains the 10 persistence/restart tests plus the existing Gate 0B state-engine tests. No external runtime dependency is required.

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

Both events are bound to the same session_id for one lifecycle.

## Local verification

From repository root:

```bash
python -m unittest discover -s experiments/gate0b -p "test_*.py" -v
```

On Windows, any installed Python 3.12+ interpreter is sufficient. Gate 0B-1/0B-2 use only the standard library.

## Next: Gate 0B-3 — initial-LIVE bootstrap policy

The remaining major domain decision is onboarding an account that is already LIVE.

Current conservative behavior:

```text
new account + LIVE observations -> stays UNKNOWN until an OFFLINE baseline exists
```

That is safe against false notifications but incomplete for the Stage Letter product because a newly followed creator may already be live.

Gate 0B-3 must define and test, explicitly:

```text
how repeated initial LIVE becomes canonical LIVE_CONFIRMED
whether a bootstrap/adopted session emits LIVE_STARTED
how notification delivery later distinguishes bootstrap from a real transition
what opened_at means when source_started_at is unavailable
how UNKNOWN during bootstrap behaves
restart/idempotency behavior for the bootstrap path
```

No notification implementation belongs in Gate 0B-3; only the domain facts required for Gate 0D should be frozen.

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
