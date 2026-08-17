# Gate 0B — State Engine + LiveSession

Status: **PASS**

## Scope

Gate 0B validates the canonical domain behavior between normalized observations and live-session state:

```text
LiveObservation
    -> State Engine
    -> LiveSession
    -> LiveEvent
```

Gate 0A progression was allowed with a known deferred real-world lifecycle capture gap. Gate 0B does not convert that waiver into fabricated source evidence; it validates deterministic domain behavior for normalized observations.

## Frozen safety invariants

```text
UNKNOWN != OFFLINE
UNKNOWN never opens or closes a LiveSession
one PlatformAccount -> at most one open LiveSession
one canonical session -> exactly one LIVE_STARTED record
one closed session -> exactly one LIVE_ENDED record
duplicate observation id -> no duplicate transition/session/event
stale observation -> no state/streak/session/event mutation
stale title/live_url metadata cannot override explicit state
```

Default Gate confirmation configuration:

```text
live_confirmations_required    = 2
offline_confirmations_required = 2
```

Thresholds are configuration, not hard-coded product truth.

---

## Gate 0B-1 — Pure state model — PASS

Normal transition chain:

```text
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

`UNKNOWN` is a pause/no-op for decisive state. It does not advance or cancel pending confirmation and never emits a session transition.

Explicit opposite evidence cancels pending transitions:

```text
LIVE_PENDING + OFFLINE -> OFFLINE_CONFIRMED
OFFLINE_PENDING + LIVE -> LIVE_CONFIRMED
```

Gate 0B-1 established duplicate-id idempotency, anti-flapping confirmation, one-open-session semantics, exact LIVE_STARTED/LIVE_ENDED pairing, and multi-cycle behavior.

Initial CI evidence:

```text
workflow  Gate 0B State Smoke
run       32005422864
result    completed / success
```

The engine exposes `EngineSnapshot` / `StateEngine.from_snapshot()` so persistence reconstructs behavior-relevant domain state without owning state-machine semantics.

---

## Gate 0B-2 — SQLite persistence + restart safety — PASS

SQLite is used only as a standard-library transaction harness. It is **not** a production database selection.

Durable projection:

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
  persist observation idempotency fact
  persist engine state + pending counters + watermark
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

Gate 0B-2 proved restart-safe pending counters, open-session durability, session-id continuity, durable observation idempotency, config continuity, account isolation, and full rollback when failure occurs after observation insert, after state write, or after session write but before event write.

---

## Gate 0B-3 — bootstrap LIVE + observation ordering — PASS

### A. Creator first observed while already LIVE

The previous conservative policy `UNKNOWN + LIVE -> UNKNOWN` is superseded.

New bootstrap chain:

```text
UNKNOWN
   |
   | initial LIVE #1
   v
BOOTSTRAP_LIVE_PENDING
   |
   | repeated decisive LIVE reaches threshold
   v
LIVE_CONFIRMED
```

If explicit OFFLINE arrives during `BOOTSTRAP_LIVE_PENDING`, bootstrap is cancelled and the engine becomes `OFFLINE_CONFIRMED`. `UNKNOWN` pauses bootstrap without advancing or cancelling it.

A confirmed bootstrap creates a canonical open LiveSession with:

```text
session.origin = BOOTSTRAP_LIVE
```

A normal observed OFFLINE -> LIVE transition creates:

```text
session.origin = TRANSITION
```

A bootstrap session records one `LIVE_STARTED` domain event for session completeness, but the event is explicitly marked:

```text
event.cause = BOOTSTRAP_LIVE
```

A true observed transition uses:

```text
event.cause = TRANSITION
```

Therefore a bootstrap discovery is **not semantically indistinguishable from a real start transition**. Gate 0D notification policy must not treat `LIVE_STARTED + cause=BOOTSTRAP_LIVE` as an ordinary “刚刚开播” notification by default.

### opened_at vs source_started_at

Gate 0B-3 freezes the time semantics:

```text
LiveSession.opened_at
    = time the canonical session becomes confirmed in Stage Letter

LiveSession.source_started_at
    = platform/provider-reported source start time when trustworthy and available
    = null when unavailable
```

`opened_at` must never be presented as an invented platform start time. If `source_started_at` is absent, later UI/API may describe the time as “检测到直播 / 状态确认时间”, not a fabricated exact开播时间.

### B. Per-account observation ordering watermark

Each StateEngine now carries:

```text
observation_watermark: datetime | null
```

Ordering rule:

```text
observation_id already seen
    -> DUPLICATE
    -> no mutation

observed_at < observation_watermark
    -> STALE
    -> record durable observation/idempotency fact
    -> do NOT change state
    -> do NOT change pending streak
    -> do NOT open/close session
    -> do NOT emit event
    -> do NOT move watermark backwards

observed_at >= watermark
    -> process normally
```

Equal timestamps are not classified stale because `observed_at` alone cannot establish ordering between equal-time observations.

A newer `UNKNOWN` observation advances the watermark while remaining a decisive-state no-op. This is intentional: an older delayed OFFLINE/LIVE response arriving after that newer observation must not regress canonical state.

Duplicate classification takes precedence over stale classification. A replayed known observation id remains DUPLICATE even if its timestamp is older than the current watermark.

The watermark, bootstrap pending state, bootstrap session origin, event cause, and source start provenance all survive SQLite restart.

---

## Gate 0B-3 acceptance evidence — PASS

The final suite proves, among other existing Gate cases:

```text
initial LIVE -> BOOTSTRAP_LIVE_PENDING                     PASS
second decisive initial LIVE -> LIVE_CONFIRMED             PASS
bootstrap session origin persisted                          PASS
bootstrap LIVE_STARTED cause persisted                      PASS
UNKNOWN pauses bootstrap                                    PASS
OFFLINE cancels bootstrap pending                           PASS
bootstrap source_started_at provenance survives restart     PASS
stale unique observation cannot mutate state                PASS
stale observation cannot advance pending streak             PASS
stale observation cannot close open session                 PASS
newer UNKNOWN advances watermark                            PASS
older delayed OFFLINE blocked after newer UNKNOWN           PASS
watermark survives restart                                  PASS
stale observation becomes durable duplicate on replay       PASS
equal timestamp is not falsely classified stale             PASS
threshold=1 immediate bootstrap/close semantics              PASS
SQLite connections close deterministically                  PASS
```

Latest CI evidence:

```text
workflow  Gate 0B Persistence Smoke
run       32006556736
head      28556b1378b562e4ba710e5f6e6754abd69676f8
result    completed / success

workflow  Gate 0B State Smoke
run       32006556771
head      28556b1378b562e4ba710e5f6e6754abd69676f8
result    completed / success

Python    3.13.15
suite     37 tests total / 37 PASS
```

The final persistence run contains no SQLite ResourceWarning from Gate code; connection lifecycle is explicitly closed.

---

## Current domain objects

### LiveObservation

```text
observation_id
status: LIVE | OFFLINE | UNKNOWN
observed_at
source
source_started_at | null
```

### LiveSession

```text
session_id
opened_at
closed_at | null
origin: TRANSITION | BOOTSTRAP_LIVE
source_started_at | null
```

### LiveEvent

```text
type: LIVE_STARTED | LIVE_ENDED
session_id
occurred_at
cause: TRANSITION | BOOTSTRAP_LIVE
```

### State ordering

```text
observation_watermark | null
```

---

## Gate 0B result — PASS

```text
Gate 0B-1 state semantics                 PASS
Gate 0B-2 restart / transaction safety    PASS
Gate 0B-3 bootstrap / ordering policy     PASS
GitHub State Smoke                        PASS
GitHub Persistence Smoke                  PASS
full Gate suite                           37 / 37 PASS
external runtime dependency               NONE
```

Known items intentionally outside Gate 0B:

```text
real source OFFLINE -> LIVE -> OFFLINE capture       Gate 0A deferred evidence gap
provider polling health / degradation policy         Gate 0C
production provider authorization/compliance         separate production track
WeChat notification eligibility/delivery truth       Gate 0D
end-to-end golden path                               Gate 0E
```

## Local verification

```bash
python -m unittest discover -s experiments/gate0b -p "test_*.py" -v
```

Gate 0B uses only the Python standard library.

## Current progression

```text
Gate 0A evidence status      DEGRADED / deferred lifecycle gap
Gate 0A progression          ALLOWED WITH KNOWN GAP
Gate 0B-1                    PASS
Gate 0B-2                    PASS
Gate 0B-3                    PASS
Gate 0B overall              PASS
Gate 0C                      READY TO START
Gate 0D                      NOT STARTED
Gate 0E                      NOT STARTED
```
