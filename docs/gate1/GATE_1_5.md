# Gate 1.5 — State / Event Persistence

Status: **PASS / CLOSED**

Entry authority: Gate 1.4 PASS / CLOSED.
Exit: Gate 1.6 CURRENT.

## 1. Goal

Gate 1.5 consumes already-durable `LiveObservation` evidence and owns canonical state reduction plus atomic `LiveSession` / `LiveEvent` persistence.

```text
LiveObservation (durable)
  -> pure LiveStateReducer
  -> transition intent
  -> atomic persistence transaction
       -> open / close LiveSession
       -> append LiveEvent
  -> Gate 1.6 notification queue
```

Gate 1.5 does not call platform providers, reinterpret provider metadata, create `NotificationDelivery`, or decide notification eligibility.

## 2. Closed slices

```text
Gate 1.5-1  Formal State Reducer + Transition Intent Contract     PASS / CLOSED
Gate 1.5-2  Observation Replay + Persistent State Reconstruction  PASS / CLOSED
Gate 1.5-3  Atomic Session / Event Persistence                    PASS / CLOSED
Gate 1.5-4  Worker Consumption + Idempotent Processing            PASS / CLOSED
Gate 1.5-5  Restart / Concurrency Acceptance                      PASS / CLOSED
```

Accepted deterministic evidence:

```text
1.5-1  12 / 12 dedicated + 295 / 295 complete Gate 1 PASS
1.5-2  13 / 13 dedicated + 308 / 308 complete Gate 1 PASS
1.5-3  13 / 13 dedicated + 321 / 321 complete Gate 1 PASS
        + real PostgreSQL transition persistence probe PASS
1.5-4  12 / 12 dedicated + 333 / 333 complete Gate 1 PASS
1.5-5  complete Gate 1 suite 345 / 345 PASS
        + real PostgreSQL restart/concurrency probe PASS
```

The complete 345-test pass includes the Gate 1.5-5 deterministic contracts.

## 3. Frozen state semantics

```text
UNKNOWN remains non-decisive
first explicit OFFLINE from UNKNOWN -> OFFLINE_CONFIRMED
initial repeated LIVE -> OPEN_SESSION / BOOTSTRAP_LIVE
OFFLINE_CONFIRMED + repeated LIVE -> OPEN_SESSION / TRANSITION
LIVE_CONFIRMED + repeated OFFLINE -> CLOSE_SESSION / TRANSITION
replayed observation_id -> duplicate / no mutation
late arrival older than watermark -> stale / no mutation
UNKNOWN newer than watermark -> watermark advances / decisive state unchanged
```

Default confirmation policy remains two LIVE confirmations and two OFFLINE confirmations.

## 4. Restart reconstruction

Process memory is disposable. Canonical reducer state is reconstructed from formal `monitor:*` observations in durable persistence order rather than sorting by `observed_at`.

The opaque replay cursor is the persisted observation row order only; it is not a domain identity and is never used as a session/event id. Historical transition intents emitted during replay are discarded and never re-persisted.

## 5. Session / event persistence

`LiveSession` BIGINT identity is allocated only by PostgreSQL using `RETURNING live_sessions.id`. Application/domain code never hashes, truncates, or derives a numeric session id from `monitor:*`, provider identity, timestamps, or other inputs.

`LiveEvent.event_id` is a deterministic bounded string idempotency key derived from account + durable observation + event type. OPEN/CLOSE session mutation and its matching canonical event are committed in one UnitOfWork.

## 6. Complete worker consumption path

```text
durable target observation
  -> reconstruct reducer immediately before target
  -> process target exactly once in reducer
  -> no intent: read-only
  -> one intent: atomic transition persistence
```

Retrying the same decisive observation reconstructs the same pre-target state and therefore the same deterministic transition/event identity. This is idempotent canonical state-output processing, not exactly-once worker execution.

## 7. Cross-process serialization

Canonical state-output mutation is serialized per account with a PostgreSQL transaction-scoped advisory lock acquired before existing-event/open-session decisions.

```text
pg_advisory_xact_lock(-canonical_account_bigint)
```

The negative canonical account BIGINT is a collision-free infrastructure lock namespace for positive formal account ids. It does not create a new persistence identity and requires no migration.

A concurrent loser waits for the winner transaction, then sees and reuses the canonical event/session. Worker execution and provider execution are still not claimed exactly once.

## 8. Accepted PostgreSQL restart/concurrency evidence

User-local acceptance at migration head `d14e7c9a5b30`:

```text
concurrent_open_reused_flags      [false, true]
concurrent_same_session           true
concurrent_same_event             true
open_state_after_concurrency      LIVE_CONFIRMED
open_state_matches_db             true
session_count_after_open          1
event_count_after_open            1
open_session_count_after_open     1
restart_open_reused_existing      true
first_offline_read_only           true
same_session_closed               true
restart_close_reused_existing     true
final_state                       OFFLINE_CONFIRMED
final_state_matches_db            true
final_session_count               1
final_event_count                 2
final_open_session_count          0
final_live_started_count          1
final_live_ended_count            1
worker_exactly_once_claimed       false
provider_exactly_once_claimed     false
production_approved               false
```

This proves restart reconstruction and canonical state-output idempotency/serialization across independent transactions. It does not prove exactly-once worker or provider execution.

## 9. Exit

```text
Gate 1.5-5  PASS / CLOSED
Gate 1.5    PASS / CLOSED
Gate 1.6    CURRENT
```

Gate 1.6 owns notification eligibility, logical delivery creation/queueing, crash-safe delivery execution, provider normalization, and WeChat delivery from already-persisted canonical `LiveEvent` facts.

## 10. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 closes without fabricating that missing provider lifecycle evidence.
