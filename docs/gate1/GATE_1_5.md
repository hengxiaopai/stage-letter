# Gate 1.5 — State / Event Persistence

Status: **CURRENT / 1.5-1 PASS / CLOSED / 1.5-2 PASS / CLOSED / 1.5-3 ATOMIC PERSISTENCE LANDED / LOCAL+POSTGRES EVIDENCE PENDING**

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
Gate 1.5-3  Atomic Session / Event Persistence                     CURRENT
Gate 1.5-4  Worker Consumption + Idempotent Processing             NOT STARTED
Gate 1.5-5  Restart / Concurrency Acceptance                       NOT STARTED
```

## 3. Accepted slices

```text
1.5-1  12 / 12 dedicated + 295 / 295 complete Gate 1 PASS
1.5-2  13 / 13 dedicated + 308 / 308 complete Gate 1 PASS
```

Gate 1.5-1 established the pure reducer and persistence-neutral OPEN/CLOSE intents. Gate 1.5-2 established restart reconstruction from formal `monitor:*` observations in durable row order, preserving late-arrival stale semantics without a hidden state table.

Result: **Gate 1.5-2 PASS / CLOSED**.

## 4. Gate 1.5-3 — CURRENT

### 4.1 Persistence-owned session identity

`LiveSession.session_id` remains a string in the formal domain boundary, but PostgreSQL owns its canonical BIGINT allocation.

The `LiveRepository` port exposes:

```text
create_session(account_id, opened_at, origin, source_started_at) -> LiveSession
get_session(session_id) -> LiveSession | None
```

The SQLAlchemy implementation inserts a new `live_sessions` row **without supplying `id`** and uses:

```text
RETURNING live_sessions.id
```

The returned PostgreSQL identity is losslessly serialized into the formal string `session_id`. Application/domain code never derives a BIGINT session id from `monitor:*`, provider ids, hashes, timestamps, or truncation.

No new migration is required for this slice; the existing PostgreSQL primary-key sequence remains the allocation authority.

### 4.2 Deterministic event identity

`LiveEvent.event_id` is a string idempotency identity and is intentionally separate from the BIGINT session identity.

Landed helper:

```text
make_live_event_id(account_id, observation_id, event_type)
```

It produces a bounded deterministic `live-event:<sha256>` value from the already-durable formal monitor observation identity plus account and event type. Hashing here is only for the string event idempotency key; it is never used to fabricate a session BIGINT.

START and END event identities are type-specific and remain stable across restart/retry.

### 4.3 Atomic transition persistence service

Landed:

```text
stage_letter/application/services/live_transition.py
```

`LiveTransitionPersistenceApplicationService.apply(observation, intent)` performs one transaction:

```text
verify PlatformAccount exists
verify exact LiveObservation is already durable
verify monitor: namespace
verify intent timestamp/status/provenance matches decisive observation
check deterministic LiveEvent id for prior completion

OPEN_SESSION:
  require no existing open session
  allocate session id in PostgreSQL
  persist LIVE_STARTED event

CLOSE_SESSION:
  require one open session
  close that same session
  persist LIVE_ENDED event

commit once
```

If the deterministic event already exists, the service reloads and validates the referenced canonical session/event and returns `reused_existing=True` without another commit.

If event insertion loses a race after this UoW has allocated/closed a session, the service raises before commit; the UoW rollback prevents a partial session-without-event commit. Distributed concurrency acceptance remains Gate 1.5-5.

### 4.4 Frozen truth rules

```text
OPEN_SESSION requires decisive LIVE observation
CLOSE_SESSION requires decisive OFFLINE observation
UNKNOWN can never enter transition persistence
intent.occurred_at == decisive observation.observed_at
OPEN source_started_at must equal persisted observation source_started_at
BOOTSTRAP_LIVE origin -> BOOTSTRAP_LIVE event cause
TRANSITION origin -> TRANSITION event cause
CLOSE cause is always TRANSITION
no provider call
no NotificationDelivery creation
```

### 4.5 Repository event contract

`LiveRepository.append_event()` returns:

```text
True  -> this transaction inserted the deterministic event id
False -> that event id was already claimed
```

The SQLAlchemy implementation retains `ON CONFLICT DO NOTHING` on `uq_g11_live_event_id` and adds `RETURNING live_events.id`, allowing the application service to distinguish a successful atomic write from an idempotency/concurrency collision.

### 4.6 PostgreSQL acceptance probe

Landed:

```text
scripts/gate15_transition_persistence_probe.py
```

The probe uses the real local PostgreSQL database at migration head `d14e7c9a5b30`, creates an isolated formal account and two durable monitor observations, then proves:

```text
OPEN allocates a real numeric session id from PostgreSQL
replaying the same OPEN reuses the existing event/session
CLOSE closes that same session id
exactly one session row exists
exactly two canonical events exist
zero open sessions remain after close
provider_called = false
notification_created = false
```

Two acceptance-script defects were exposed during local execution before PostgreSQL evidence could be accepted: first, the probe referenced physical database column names as Python ORM attributes; second, SQLAlchemy result-row keys followed the underlying mapped column names rather than the intended domain attribute names. Both are probe-only defects, not runtime/schema failures.

The probe now selects mapped session fields with explicit stable labels:

```text
id                -> session_id
opened_at         -> opened_at
closed_at         -> closed_at
origin            -> origin
source_started_at -> source_started_at
```

This prevents ORM attribute names and physical column names (`started_at` / `ended_at`) from leaking into result-row access. Probe rows are removed afterward. This remains non-production evidence only.

### 4.7 Landed deterministic contracts

```text
tests/gate1/test_gate15_transition_persistence.py       12 tests
tests/gate1/test_gate15_transition_probe_contract.py     1 test
```

The contracts cover deterministic event identity, persistence-owned session allocation, atomic OPEN, bootstrap provenance, atomic CLOSE, event reuse, missing/mismatched durable evidence, monitor/status gates, missing open-session failure, no partial commit after event collision, application boundary purity, and explicit result labels in the PostgreSQL acceptance probe.

Accepted entering baseline is 308 tests. Thirteen new tests raise the expected complete Gate 1 suite to:

```text
321 / 321
```

### 4.8 Acceptance — Gate 1.5-3

```text
A. Gate 1.5-2 PASS / CLOSED                         PASS
B. PostgreSQL-owned BIGINT session allocation       PASS / CODE
C. no derived/fabricated numeric session identity   PASS / CONTRACT
D. deterministic string LiveEvent idempotency       PASS / CONTRACT
E. OPEN session + LIVE_STARTED one-UoW atomicity    PASS / CONTRACT
F. CLOSE session + LIVE_ENDED one-UoW atomicity     PASS / CONTRACT
G. existing event reuse without duplicate commit    PASS / CONTRACT
H. UNKNOWN/provider/notification boundaries         PASS / CONTRACT
I. dedicated Gate 1.5-3 contracts                   PENDING / 13
J. complete Gate 1 suite                            PENDING / expected 321
K. real PostgreSQL transition persistence probe     PENDING / LOCAL POSTGRES
```

Gate 1.5-3 remains CURRENT until I-K pass.

## 5. Next slice

Gate 1.5-4 will connect durable observation consumption, reconstruction, reducer processing, and the atomic transition persistence service into one worker use-case. It must ensure an observation that emits no intent stays read-only, a decisive transition is applied idempotently, and retries never replay historical intents into duplicate session/event output.

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
partial commit of session without matching event
creating notification delivery from state reducer/replay/transition persistence
relying on process memory as the only restart truth
formal runtime importing experiments or platform_adapters
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.5 preserves that caveat while using the accepted deterministic Gate 0B state semantics.
