# Gate 1.5 — State / Event Persistence

Status: **CURRENT / 1.5-1 STATE REDUCER LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.5-1  Formal State Reducer + Transition Intent Contract     CURRENT
Gate 1.5-2  Observation Replay + Persistent State Reconstruction  NOT STARTED
Gate 1.5-3  Atomic Session / Event Persistence                     NOT STARTED
Gate 1.5-4  Worker Consumption + Idempotent Processing             NOT STARTED
Gate 1.5-5  Restart / Concurrency Acceptance                       NOT STARTED
```

## 3. Gate 1.5-1 — CURRENT

### 3.1 Formal runtime

Landed:

```text
stage_letter/domain/state_engine.py
```

The reducer is pure domain code. It imports only formal live-domain types and owns no SQLAlchemy, worker, API, provider, queue, or legacy runtime concern.

Frozen engine states match the accepted Gate 0B oracle vocabulary:

```text
UNKNOWN
BOOTSTRAP_LIVE_PENDING
OFFLINE_CONFIRMED
LIVE_PENDING
LIVE_CONFIRMED
OFFLINE_PENDING
```

Default confirmation policy remains:

```text
LIVE confirmations required      2
OFFLINE confirmations required   2
```

### 3.2 Transition semantics

The reducer emits only persistence-neutral intents:

```text
OPEN_SESSION
CLOSE_SESSION
```

Rules:

```text
first explicit OFFLINE from UNKNOWN -> OFFLINE_CONFIRMED
initial repeated LIVE               -> OPEN_SESSION / BOOTSTRAP_LIVE
OFFLINE_CONFIRMED + repeated LIVE   -> OPEN_SESSION / TRANSITION
LIVE_CONFIRMED + repeated OFFLINE   -> CLOSE_SESSION / TRANSITION
UNKNOWN                             -> accepted evidence, no decisive transition
explicit LIVE during OFFLINE_PENDING -> cancel pending close
explicit OFFLINE during LIVE_PENDING -> cancel pending open
```

`source_started_at` is carried only on `OPEN_SESSION` and only when it already exists on the decisive provider observation. It is never invented by the reducer.

### 3.3 Ordering and idempotency semantics

The Gate 0B ordering contract is preserved:

```text
replayed observation_id -> duplicate, no state mutation
new observation older than watermark -> stale, no state mutation
UNKNOWN newer than watermark -> watermark advances, decisive state unchanged
```

The reducer snapshot is in-memory state only. Gate 1.5-2 must reconstruct equivalent reducer state from durable persistence; Gate 1.5-1 does not introduce a new persistence entity or hidden state table.

### 3.4 ID allocation boundary

Gate 1.5-1 deliberately does **not** allocate `LiveSession.session_id` or `LiveEvent.event_id`.

The formal persistence schema uses BIGINT-backed session identities and string event identities. Hashing, truncation, fake numeric IDs, or converting `monitor:*` observation ids into BIGINTs is forbidden. Gate 1.5-3 must define a lossless persistence-owned allocation/idempotency contract before final session/event writes are enabled.

### 3.5 Deterministic contracts

Landed:

```text
tests/gate1/test_gate15_state_reducer.py  12 tests
```

The contracts verify confirmation thresholds, UNKNOWN behavior, bootstrap adoption, real transition open, confirmed close, cancellation behavior, duplicate/stale ordering, snapshot restoration, and pure-domain dependency boundaries.

Accepted entering baseline is 283 tests. Twelve new tests raise the expected complete Gate 1 suite to:

```text
295 / 295
```

### 3.6 Acceptance — Gate 1.5-1

```text
A. Gate 1.4 PASS / CLOSED                      PASS
B. pure formal reducer                         PASS / CODE
C. Gate 0B state vocabulary preserved          PASS / CONTRACT
D. UNKNOWN remains non-decisive                 PASS / CONTRACT
E. duplicate/stale ordering preserved           PASS / CONTRACT
F. bootstrap vs transition intent distinguished PASS / CONTRACT
G. no session/event ID fabrication              PASS / CONTRACT
H. dedicated Gate 1.5-1 contracts               PENDING / 12
I. complete Gate 1 suite                        PENDING / expected 295
```

Gate 1.5-1 remains CURRENT until H-I pass.

## 4. Next slice

Gate 1.5-2 will define how durable observations plus persisted open-session/event facts reconstruct reducer state after process restart. It must preserve streak and watermark semantics without inventing a new canonical domain entity or silently relying on process memory.

## 5. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
UNKNOWN converted to OFFLINE
single weak LIVE/OFFLINE sample bypassing configured confirmation
provider metadata deciding canonical state
Gate 1.5 calling provider adapters
hashing/truncating/faking BIGINT session identity
inventing historical session origin/event cause
creating notification delivery from state reducer
relying on process memory as the only restart truth
formal runtime importing experiments or platform_adapters
```

## 6. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 preserves that caveat while using the accepted deterministic Gate 0B state semantics.
