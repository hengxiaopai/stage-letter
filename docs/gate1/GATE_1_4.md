# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **CURRENT / 1.4-1 PASS / 1.4-2 PASS / CLOSED / 1.4-3 SCHEDULER POLICY LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.3 PASS / CLOSED.

## 1. Goal

Gate 1.4 connects the accepted four-platform adapter framework to durable monitoring without allowing scheduler mechanics, provider failures, or weak metadata to rewrite canonical live truth.

Target pipeline:

```text
explicitly enabled PlatformAccount
  -> deterministic target discovery
  -> scheduler/probe request
  -> formal AdapterRegistry
  -> LivePlatformAdapter.get_live_snapshot()
  -> normalized LiveSnapshot
  -> durable LiveObservation
  -> later Gate 1.5 state/session/event persistence
```

Gate 1.4 owns target discovery, scheduling/probe orchestration, and observation ingestion only. It does not create/close LiveSession, emit LiveEvent, or decide notification eligibility.

## 2. Internal slices

```text
Gate 1.4-1  Monitoring Target Discovery + Paging Contract        PASS / CLOSED
Gate 1.4-2  Probe Request + LiveSnapshot -> LiveObservation      PASS / CLOSED
Gate 1.4-3  Scheduler Cadence / Concurrency / Backoff            CURRENT
Gate 1.4-4  Worker Composition + Four-platform Runtime Wiring    NOT STARTED
Gate 1.4-5  Observation Durability / Restart Acceptance          NOT STARTED
```

## 3. Gate 1.4-1 — PASS / CLOSED

Accepted user-local evidence:

```text
Gate 1.4 monitoring-target contracts   8 / 8 PASS
complete Gate 1 suite                243 / 243 PASS
```

Accepted target-selection truth:

```text
platform_accounts.is_disabled = false -> eligible monitoring target
platform_accounts.is_disabled = true  -> excluded
platform_accounts.is_disabled = null  -> not silently promoted to enabled
```

Target discovery remains keyset-paged by canonical account id, read-only, provider-free, and notification-independent.

Result: **Gate 1.4-1 PASS / CLOSED**.

## 4. Gate 1.4-2 — PASS / CLOSED

Accepted user-local evidence:

```text
probe -> observation contracts   10 / 10 PASS
complete Gate 1 suite           253 / 253 PASS
```

Accepted probe identity and persistence contract:

```text
one logical probe request = probe_id + account_id
retry of same logical probe reuses same probe_id
LiveObservation.observation_id <- probe_id
```

The probe application performs durable re-use checks by `(account_id, observation_id)` before and after provider I/O. Provider work remains outside the UnitOfWork. Disabled/missing accounts fail before provider I/O; identity changes while a request is in flight prevent stale persistence.

Only formal normalized facts are copied from LiveSnapshot into LiveObservation:

```text
status
observed_at
source
source_started_at
```

`UNKNOWN` remains `UNKNOWN`. Room/title/page metadata does not override state. Adapter identity mismatch is an invariant failure rather than a fabricated observation.

The historical database uniqueness key is still source-scoped. Logical cross-source lookup detects ambiguous duplicate durable rows rather than silently selecting one. True concurrent scheduling mechanics are handled in 1.4-3/1.4-5; 1.4-2 itself does not claim distributed single-flight.

Result: **Gate 1.4-2 PASS / CLOSED**.

## 5. Gate 1.4-3 — CURRENT

### Landed runtime

```text
workers/monitoring/__init__.py
workers/monitoring/scheduler.py
```

Landed deterministic contracts:

```text
tests/gate1/test_gate14_scheduler.py  10 tests
```

### Scheduler policy

The current formal defaults are configurable worker mechanics, not live-state truth or a production SLA:

```text
cadence_seconds            30
max_concurrency            16
per_platform_concurrency    4
max_attempts                3
base_backoff_seconds        1
max_backoff_seconds         8
page_size                 100
```

Policy rejects invalid/non-positive limits before scheduling work. Backoff is deterministic capped exponential (`1s -> 2s -> 4s`, capped by configuration) so tests and retries remain reproducible.

### Stable logical probe identity

For each `(cycle_id, account_id)`, the scheduler derives one bounded deterministic probe id using SHA-256:

```text
monitor:<64 hex chars>
```

Every retry reuses the exact same MonitoringProbeRequest and therefore the same durable observation identity. A new monitoring cycle receives a different logical probe id.

### Bounded concurrency

The scheduler enforces both:

```text
global concurrency limit
per-platform concurrency limit
```

No platform can consume more than the configured platform semaphore even if global capacity remains available.

### Single-flight scope

Concurrent calls inside one formal scheduler process for the same `(account_id, probe_id)` share one in-flight task, so the same logical probe is not executed twice inside that process.

This is deliberately **not** described as distributed exactly-once provider execution. A second OS process could still issue the same provider request. Durable duplicate behavior across process/restart boundaries remains an explicit Gate 1.4-5 acceptance concern. Gate 1.4 must not claim stronger semantics than the evidence supports.

### Retry semantics

Scheduler retries apply only to escaped transient orchestration exceptions:

```text
TimeoutError
ConnectionError
```

Retries preserve the same logical probe id and release concurrency slots before sleeping. Other application/invariant failures are not retried.

A successfully normalized `UNKNOWN` observation is a valid monitoring fact and is **not** retried merely because its status is UNKNOWN. This preserves the accepted adapter rule that provider ambiguity/failure can legitimately normalize to UNKNOWN.

If all scheduler-level retries are exhausted, the scheduler returns an explicit failed outcome and does not fabricate an OFFLINE or UNKNOWN observation on its own. Canonical observation truth remains owned by the formal adapter/probe pipeline.

### Paging / cycle behavior

`run_cycle(cycle_id)` consumes all explicitly enabled targets through the accepted keyset paging service and schedules one logical probe per account. Empty/invalid cycle ids fail before target discovery.

### Boundary ownership

The scheduler imports application services/domain account identity only. It does not import SQLAlchemy, provider SDKs, legacy `platform_adapters`, Gate 0 experiments, sessions/events/notifications, room/title metadata, or provider-specific status constants.

### Acceptance — Gate 1.4-3

Accepted entering baseline is 253 tests. Ten new scheduler contracts raise the expected complete Gate 1 suite to 263.

```text
A. Gate 1.4-2 PASS / CLOSED                         PASS
B. deterministic cadence/backoff policy             PASS / CODE
C. stable cycle/account -> probe_id                  PASS / CONTRACT
D. same-process same-probe single-flight             PASS / CODE
E. global bounded concurrency                        PASS / CODE
F. per-platform bounded concurrency                  PASS / CODE
G. retry reuses exact logical probe                  PASS / CONTRACT
H. successful UNKNOWN is not retried                 PASS / CONTRACT
I. retry exhaustion fabricates no observation        PASS / CONTRACT
J. no live-state/session/event/notification ownership PASS / CONTRACT
K. dedicated Gate 1.4-3 contracts                   PENDING / 10
L. complete Gate 1 suite                            PENDING / expected 263
```

Gate 1.4-3 remains CURRENT until K-L pass.

## 6. Next slices

Gate 1.4-4 will wire the accepted four-platform `AdapterRegistry`, monitoring target service, probe service, and scheduler into the formal worker composition root without triggering provider I/O at construction time.

Gate 1.4-5 will then validate durable observation behavior across restart/crash/concurrent-process boundaries and close any remaining logical-probe duplicate risk before Gate 1.4 can be accepted for production scheduling.

## 7. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy/null eligibility guessed as enabled
follow or notification preference used as monitoring eligibility truth
provider failure converted to OFFLINE
provider I/O inside DB transaction
scheduler retry generating a new logical observation id
UNKNOWN treated as scheduler failure merely because status is UNKNOWN
same-process duplicate logical probe executed twice
cross-process exactly-once claimed without evidence
provider metadata used to override explicit LiveSnapshot.status
snapshot identity mismatch persisted under another account
Gate 1.4 creating LiveSession / LiveEvent
Gate 1.4 deciding notification eligibility
formal runtime importing legacy platform_adapters or experiments
```

## 8. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 must preserve that status rather than fabricating historical lifecycle evidence.
