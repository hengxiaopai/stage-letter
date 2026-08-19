# Gate 1.5 — State / Event Persistence

Status: **CURRENT / 1.5-1 PASS / CLOSED / 1.5-2 PASS / CLOSED / 1.5-3 PASS / CLOSED / 1.5-4 PASS / CLOSED / 1.5-5 RESTART+CONCURRENCY LANDED / LOCAL+POSTGRES EVIDENCE PENDING**

Entry authority: Gate 1.4 PASS / CLOSED.

## 1. Goal

Gate 1.5 consumes already-durable `LiveObservation` evidence and owns canonical state reduction plus atomic `LiveSession` / `LiveEvent` persistence.

```text
LiveObservation (durable)
  -> pure LiveStateReducer
  -> transition intent
  -> atomic persistence transaction
       -> open / close LiveSession
       -> append LiveEvent
  -> later Gate 1.6 notification queue
```

Gate 1.5 does not call platform providers, does not reinterpret provider metadata, and does not decide notification eligibility.

## 2. Internal slices

```text
Gate 1.5-1  Formal State Reducer + Transition Intent Contract     PASS / CLOSED
Gate 1.5-2  Observation Replay + Persistent State Reconstruction  PASS / CLOSED
Gate 1.5-3  Atomic Session / Event Persistence                    PASS / CLOSED
Gate 1.5-4  Worker Consumption + Idempotent Processing            PASS / CLOSED
Gate 1.5-5  Restart / Concurrency Acceptance                      CURRENT
```

## 3. Accepted slices

```text
1.5-1  12 / 12 dedicated + 295 / 295 complete Gate 1 PASS
1.5-2  13 / 13 dedicated + 308 / 308 complete Gate 1 PASS
1.5-3  13 / 13 dedicated + 321 / 321 complete Gate 1 PASS
        + real PostgreSQL transition persistence probe PASS
1.5-4  12 / 12 dedicated + 333 / 333 complete Gate 1 PASS
```

Gate 1.5-3 accepted PostgreSQL evidence proves database-owned numeric session allocation, idempotent OPEN replay, same-session CLOSE, one session row, two canonical events, zero open sessions after close, and no provider/notification activity.

Gate 1.5-4 accepted user-local evidence proves the complete worker consumption use-case reconstructs state immediately before one target observation, suppresses historical intents, keeps no-intent observations read-only, and delegates exactly one new decisive intent into the accepted atomic transition persistence path.

Result: **Gate 1.5-4 PASS / CLOSED**.

## 4. Gate 1.5-5 — CURRENT

### 4.1 Remaining concurrency risk entering this slice

Gate 1.5-3 already makes event identity deterministic and preserves one-UoW session/event atomicity. Gate 1.5-4 makes retry deterministic from durable observation history.

However, two independent worker executions can reconstruct the same pre-target state at the same time and both attempt the same decisive transition. Database uniqueness alone prevents some duplicates, but without serialization an OPEN race can still collide first on the one-open-session constraint and surface an infrastructure exception before the losing worker can observe and reuse the canonical event/session.

Gate 1.5-5 therefore serializes **canonical state-output mutation**, not worker/provider execution.

### 4.2 Transaction-scoped per-account transition lock

`LiveRepository` now exposes the infrastructure-free coordination port:

```text
acquire_transition_lock(account_id) -> None
```

The PostgreSQL implementation uses:

```text
pg_advisory_xact_lock(<negative canonical account BIGINT>)
```

Formal account ids are positive PostgreSQL BIGINTs. Their negative value is used only as a collision-free infrastructure lock namespace for this transaction-scoped coordination primitive. No hashing, truncation, alternate domain identity, or new persistence entity is introduced.

The lock is released automatically by PostgreSQL when the surrounding UnitOfWork commits or rolls back. The repository lock method itself never commits or rolls back.

### 4.3 Serialized transition application

`LiveTransitionPersistenceApplicationService.apply()` now acquires the account transition lock before reading the durable observation, deterministic event, or open-session state.

The concurrent winner therefore performs the canonical session/event mutation and commits. A waiting execution acquires the same lock afterward, then sees the already-persisted deterministic event/session and returns:

```text
reused_existing = True
```

This closes duplicate canonical session/event output for the same account transition across independent database transactions while preserving the accurate boundary:

```text
canonical state output is idempotent/serialized
worker execution is NOT exactly once
provider execution is NOT exactly once
```

No new Alembic migration is required. The migration head remains:

```text
d14e7c9a5b30
```

### 4.4 Restart + concurrency PostgreSQL acceptance probe

Landed:

```text
scripts/gate15_restart_concurrency_probe.py
```

The real probe uses the formal worker composition and local PostgreSQL to exercise the complete path:

```text
persist OFFLINE + LIVE + decisive LIVE
  -> concurrently consume the same decisive LIVE twice
  -> exactly one canonical session/event winner
  -> loser reuses the same session/event
  -> reconstruct full reducer state == LIVE_CONFIRMED/session_open
  -> DB graph == 1 session / 1 LIVE_STARTED / 1 open session

restart engine + rebuild worker services
  -> consume same decisive LIVE again
  -> reuse existing canonical output

persist OFFLINE + decisive OFFLINE
  -> first OFFLINE is read-only pending confirmation
  -> second OFFLINE closes the same session + emits LIVE_ENDED

restart again
  -> consume same decisive OFFLINE again
  -> reuse existing close output
  -> reconstruct full reducer state == OFFLINE_CONFIRMED/session_open false
  -> DB graph == 1 session / 2 events / 0 open sessions
```

The probe explicitly reports:

```text
worker_exactly_once_claimed   false
provider_exactly_once_claimed false
production_approved           false
```

It removes isolated probe rows afterward.

### 4.5 Reducer/DB graph cross-check

Gate 1.5-5 does not accept restart idempotency merely because event counts look correct. The real probe cross-checks the reconstructed reducer snapshot against the persisted canonical graph at two lifecycle points:

```text
LIVE_CONFIRMED + session_open=True
  <-> exactly one open LiveSession + exactly one LIVE_STARTED

OFFLINE_CONFIRMED + session_open=False
  <-> same LiveSession closed + one LIVE_STARTED + one LIVE_ENDED
```

A mismatch is FAIL even if individual inserts were successful.

### 4.6 Landed deterministic contracts

```text
tests/gate1/test_gate15_restart_concurrency.py  12 tests
```

The contracts cover the async transition-lock port, PostgreSQL transaction-scoped advisory lock, collision-free negative account lock key, no repository-owned commit/rollback, lock-before-decision ordering, application boundary purity, concurrent same-target probe shape, runtime restart boundaries, reducer/DB open-state cross-check, final closed-state cross-check, read-only first OFFLINE, same-session CLOSE, and explicit no-exactly-once claims.

Accepted entering baseline is 333 tests. Twelve new tests raise the expected complete Gate 1 suite to:

```text
345 / 345
```

### 4.7 Acceptance — Gate 1.5-5

```text
A. Gate 1.5-4 PASS / CLOSED                              PASS
B. transaction-scoped per-account transition lock        PASS / CODE
C. lock acquired before canonical event/session decision PASS / CONTRACT
D. no new persistence identity or migration               PASS / CONTRACT
E. concurrent loser reuses canonical winner               PASS / CONTRACT SHAPE
F. reducer/open-session graph cross-check                  PASS / CONTRACT SHAPE
G. restart retry uses durable truth, not process memory    PASS / CONTRACT SHAPE
H. no worker/provider exactly-once claim                   PASS / CONTRACT
I. dedicated Gate 1.5-5 contracts                         PENDING / 12
J. complete Gate 1 suite                                  PENDING / expected 345
K. real PostgreSQL restart/concurrency probe               PENDING / LOCAL POSTGRES
```

Gate 1.5 remains CURRENT until I-K pass.

## 5. Gate 1.5 exit

If the deterministic suite and real PostgreSQL restart/concurrency probe pass:

```text
Gate 1.5-5  PASS / CLOSED
Gate 1.5    PASS / CLOSED
Gate 1.6    CURRENT
```

Gate 1.6 then owns notification queue and WeChat delivery from already-persisted canonical `LiveEvent` facts. Gate 1.5 must not create `NotificationDelivery`.

## 6. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
UNKNOWN converted to OFFLINE
single weak LIVE/OFFLINE sample bypassing configured confirmation
provider metadata deciding canonical state
Gate 1.5 calling provider adapters
sorting replay solely by observed_at and losing late-arrival stale semantics
legacy/manual observation silently entering formal reconstruction
replaying historical intents into duplicate session/event writes
processing the target observation inside prior reconstruction
hashing/truncating/faking BIGINT session identity
inventing historical session origin/event cause
partial commit of session without matching event
creating NotificationDelivery from state reduction/consumption
relying on process memory as the only restart truth
claiming exactly-once worker/provider execution from serialization/idempotency
formal runtime importing experiments or platform_adapters
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 preserves that caveat while using the accepted deterministic Gate 0B state semantics.
