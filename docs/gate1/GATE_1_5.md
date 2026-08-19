# Gate 1.5 — State / Event Persistence

Status: **CURRENT / 1.5-1 PASS / CLOSED / 1.5-2 PASS / CLOSED / 1.5-3 PASS / CLOSED / 1.5-4 CONSUMPTION LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.5-3  Atomic Session / Event Persistence                     PASS / CLOSED
Gate 1.5-4  Worker Consumption + Idempotent Processing             CURRENT
Gate 1.5-5  Restart / Concurrency Acceptance                       NOT STARTED
```

## 3. Accepted slices

```text
1.5-1  12 / 12 dedicated + 295 / 295 complete Gate 1 PASS
1.5-2  13 / 13 dedicated + 308 / 308 complete Gate 1 PASS
1.5-3  13 / 13 dedicated + 321 / 321 complete Gate 1 PASS
        + real PostgreSQL transition persistence probe PASS
```

Gate 1.5-3 accepted PostgreSQL evidence proves database-owned numeric session allocation, idempotent OPEN replay, same-session CLOSE, one session row, two canonical events, zero open sessions after close, and no provider/notification activity. The two earlier acceptance-probe defects were probe-only ORM/result-label issues and are regression-locked.

Result: **Gate 1.5-3 PASS / CLOSED**.

## 4. Gate 1.5-4 — CURRENT

### 4.1 Consumption boundary

Gate 1.5-4 connects durable observation evidence to the accepted reducer and transition persistence services without re-emitting historical intents.

Landed:

```text
stage_letter/application/services/live_consumption.py
```

`LiveObservationConsumptionApplicationService.consume(account_id, observation_id)` performs:

```text
locate one durable formal monitor observation
reconstruct reducer state immediately BEFORE that observation
process exactly that target observation once in the reducer
if no intent -> read-only result
if one intent -> delegate to atomic transition persistence
if more than one intent -> explicit invariant failure
```

The target observation itself is deliberately excluded from reconstruction. This prevents it from being classified as a duplicate before the consumer gets a chance to decide its new transition.

### 4.2 Point-in-time reconstruction

`StateReconstructionApplicationService` now also exposes:

```text
reconstruct_before_observation(account_id, observation_id)
```

It pages formal `monitor:*` observations in durable sequence order and stops when it reaches the requested target. The returned `ObservationConsumptionPoint` contains:

```text
prior  -> EngineSnapshot reconstructed only from earlier durable observations
target -> exact ObservationReplayRecord to consume
```

Historical intents emitted while rebuilding `prior` are discarded exactly as in Gate 1.5-2. They are never forwarded to transition persistence.

### 4.3 Idempotent retry semantics

Retrying the same decisive target performs the same deterministic sequence:

```text
same durable prior history
  -> same pre-target reducer state
  -> same target observation
  -> same transition intent
  -> same deterministic LiveEvent.event_id
```

The Gate 1.5-3 persistence service therefore reuses the already-persisted canonical event/session on retry instead of creating duplicates.

This is idempotent state-output processing. It does not claim exactly-once worker execution.

### 4.4 No-intent observations stay read-only

The consumer does not open a UnitOfWork or commit merely because an observation exists. `UNKNOWN`, first OFFLINE, pending confirmation samples, cancelled transitions, duplicate/stale reducer outcomes, and any other no-intent result remain read-only at the state-output layer.

A historical transition that occurred before the target may be reconstructed semantically in memory, but its historical intent is not re-persisted.

### 4.5 Worker composition

`workers/composition.py` now exposes, from the same lazy UoW factory:

```text
state_reconstruction
live_transitions
live_observation_consumer
```

Construction still performs no database/provider I/O. The consumer has no adapter registry, provider gateway, notification repository, or queue dependency.

### 4.6 Landed deterministic contracts

```text
tests/gate1/test_gate15_observation_consumption.py  12 tests
```

The contracts cover pre-target reconstruction, missing/non-monitor target rejection, no-intent OFFLINE/UNKNOWN behavior, bootstrap and real transition OPEN emission, stale-target suppression, historical-intent discard, deterministic retry delegation, worker wiring without construction I/O, and dependency-boundary purity.

Accepted entering baseline is 321 tests. Twelve new tests raise the expected complete Gate 1 suite to:

```text
333 / 333
```

### 4.7 Acceptance — Gate 1.5-4

```text
A. Gate 1.5-3 PASS / CLOSED                           PASS
B. target excluded from historical reconstruction     PASS / CONTRACT
C. historical intents never forwarded to persistence  PASS / CONTRACT
D. no-intent observations remain read-only            PASS / CONTRACT
E. decisive target delegates exactly one new intent   PASS / CONTRACT
F. retry reproduces same target intent                 PASS / CONTRACT
G. worker construction remains side-effect free        PASS / CONTRACT
H. no provider/notification dependency                 PASS / CONTRACT
I. dedicated Gate 1.5-4 contracts                     PENDING / 12
J. complete Gate 1 suite                              PENDING / expected 333
```

Gate 1.5-4 remains CURRENT until I-J pass.

## 5. Next slice

Gate 1.5-5 will provide real PostgreSQL restart/concurrency acceptance for the complete consumption path. It will cross-check reconstructed reducer state against persisted open-session/event facts, exercise retry after process restart, and test concurrent consumption of the same decisive observation without claiming exactly-once worker execution.

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
claiming exactly-once worker execution from idempotent persistence
formal runtime importing experiments or platform_adapters
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 preserves that caveat while using the accepted deterministic Gate 0B state semantics.
