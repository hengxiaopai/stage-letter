# Gate 1.5 — State / Event Persistence

Status: **CURRENT / 1.5-1 PASS / CLOSED / 1.5-2 RECONSTRUCTION LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.5-2  Observation Replay + Persistent State Reconstruction  CURRENT
Gate 1.5-3  Atomic Session / Event Persistence                     NOT STARTED
Gate 1.5-4  Worker Consumption + Idempotent Processing             NOT STARTED
Gate 1.5-5  Restart / Concurrency Acceptance                       NOT STARTED
```

## 3. Gate 1.5-1 — PASS / CLOSED

Accepted user-local deterministic evidence:

```text
Gate 1.5 state reducer contracts   12 / 12 PASS
complete Gate 1 suite             295 / 295 PASS
```

The pure formal reducer preserves the accepted Gate 0B vocabulary and confirmation rules without importing `experiments/*`. `UNKNOWN` remains non-decisive, duplicate/stale ordering is preserved, bootstrap LIVE remains distinct from a real transition, and the reducer emits persistence-neutral `OPEN_SESSION` / `CLOSE_SESSION` intents without allocating session/event identifiers.

Result: **Gate 1.5-1 PASS / CLOSED**.

## 4. Gate 1.5-2 — CURRENT

### 4.1 Reconstruction authority

Gate 1.5-2 does not add a hidden state table or a new canonical domain entity. Reducer process memory is disposable. After restart, state is rebuilt from already-durable formal monitoring observations.

Only scheduler observations in the accepted namespace participate:

```text
monitor:<logical-id>
```

Legacy/manual non-monitor observations are excluded from canonical reconstruction because their participation in the formal scheduler pipeline is not provable.

### 4.2 Durable replay order

The Gate 0B stale-observation rule depends on arrival order, not merely `observed_at` sorting. Therefore the repository exposes an infrastructure-free replay record:

```text
ObservationReplayRecord(
  sequence=<opaque persistence cursor>,
  observation=<LiveObservation>,
)
```

`sequence` is not a domain identity and is never used as a session/event id. The SQLAlchemy repository maps the existing `live_observations.id` to this opaque cursor and pages by:

```text
platform_account_id = account
observation_id LIKE 'monitor:%'
id > after_sequence
ORDER BY id ASC
LIMIT page_size
```

This allows a late-arriving observation with an older `observed_at` timestamp to be replayed after the newer durable fact and remain stale exactly as it was classified by the reducer contract.

### 4.3 Read-only reconstruction service

Landed:

```text
stage_letter/application/services/state_replay.py
```

`StateReconstructionApplicationService`:

```text
1. verifies the PlatformAccount exists
2. starts a fresh LiveStateReducer
3. pages formal monitor observations in durable sequence order
4. replays each observation through the reducer
5. discards historical transition intents
6. returns only the reconstructed EngineSnapshot + replay metadata
```

Historical intents are deliberately not exposed for persistence. Gate 1.5-3 owns writes for newly consumed observations; replay must never duplicate historical sessions/events.

The service performs no commit, no session/event write, no provider call, and no notification action.

### 4.4 Restart truth and current limitation

For this slice, durable monitoring observations are sufficient to reconstruct reducer state, streaks, seen observation ids, watermark, and the reducer's `session_open` semantic flag.

Gate 1.5-2 does **not yet** assert that an already-persisted `LiveSession` / `LiveEvent` graph matches the reconstructed reducer. That cross-check becomes meaningful only after Gate 1.5-3 begins writing canonical session/event rows and is therefore deferred to Gate 1.5-5 restart/concurrency acceptance.

This avoids using nonexistent future persistence output as an input prerequisite for reconstruction.

### 4.5 Landed contracts

```text
tests/gate1/test_gate15_state_reconstruction.py  13 tests
```

The contracts verify:

```text
positive opaque replay sequence
async replay repository port
monitor-only SQL filtering
stable durable-id ordering
empty-history reconstruction
OFFLINE reconstruction
bootstrap LIVE reconstruction
OFFLINE -> LIVE reconstruction
UNKNOWN watermark semantics
late stale observation preservation
multi-page replay without commits
wrong-account/non-monitor evidence rejection
missing-account failure + application boundary purity
```

Accepted entering baseline is 295 tests. Thirteen new tests raise the expected complete Gate 1 suite to:

```text
308 / 308
```

### 4.6 Acceptance — Gate 1.5-2

```text
A. Gate 1.5-1 PASS / CLOSED                         PASS
B. no hidden canonical state table                  PASS / CONTRACT
C. formal monitor observations are replay authority PASS / CONTRACT
D. persistence order preserves stale semantics      PASS / CONTRACT
E. replay is read-only                              PASS / CONTRACT
F. historical intents are not persisted             PASS / CONTRACT
G. application layer remains infrastructure-free    PASS / CONTRACT
H. dedicated Gate 1.5-2 contracts                   PENDING / 13
I. complete Gate 1 suite                            PENDING / expected 308
```

Gate 1.5-2 remains CURRENT until H-I pass.

## 5. Next slice

Gate 1.5-3 will define persistence-owned `LiveSession` BIGINT allocation plus deterministic `LiveEvent.event_id` idempotency, then atomically apply one newly emitted transition intent with its canonical session/event mutation. It must not derive BIGINT ids from `monitor:*`, hash/truncate provider identity, or partially commit session and event output.

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
hashing/truncating/faking BIGINT session identity
inventing historical session origin/event cause
creating notification delivery from state reducer/replay
relying on process memory as the only restart truth
formal runtime importing experiments or platform_adapters
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 preserves that caveat while using the accepted deterministic Gate 0B state semantics.
