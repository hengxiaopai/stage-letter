# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **CURRENT / 1.4-1 PASS / CLOSED / 1.4-2 PROBE->OBSERVATION LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.4-2  Probe Request + LiveSnapshot -> LiveObservation      CURRENT
Gate 1.4-3  Scheduler Cadence / Concurrency / Backoff            NOT STARTED
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

## 4. Gate 1.4-2 — CURRENT

### Landed runtime

```text
stage_letter/application/services/monitoring_probe.py
stage_letter/application/ports.py
stage_letter/infrastructure/db/repositories/live.py
stage_letter/application/services/__init__.py
```

Landed deterministic contracts:

```text
tests/gate1/test_gate14_probe_observation.py  10 tests
```

### Probe identity contract

One `MonitoringProbeRequest` targets exactly one formal `PlatformAccount`:

```text
probe_id + account_id
```

`probe_id` is a scheduler-owned logical request id. A retry of the same logical probe **must reuse the same probe_id**. Gate 1.4-2 stores that value directly as `LiveObservation.observation_id`.

The application validates that `probe_id` is non-empty and fits the existing 255-character observation-id column. It does not invent provider ids or derive canonical state from the probe id.

### Sequential retry/idempotency contract

Before provider I/O the service reads durable observation state by:

```text
(account_id, observation_id)
```

without requiring the provider source to match. If the observation already exists, the service returns it and does not call the provider or commit a new row.

After provider I/O it performs the same logical lookup again before append/commit. This closes the common retry case where another worker completed while the provider request was in flight.

The historical DB uniqueness constraint remains source-scoped. Therefore **true concurrent same-probe races with differing provider-source values are not yet claimed solved by 1.4-2**. Gate 1.4-3 owns scheduler concurrency/single-flight semantics and must close that race before production scheduling is accepted.

If the repository detects more than one durable row for the same `(account_id, observation_id)` across sources, it raises explicit mapping ambiguity rather than silently selecting one.

### Provider / transaction boundary

Flow is intentionally split:

```text
read UoW: existing observation + account eligibility
  -> close DB transaction
  -> adapter lookup + get_live_snapshot(account)
  -> validate snapshot platform/provider identity
  -> write UoW: re-check existing observation + persist + commit
```

Provider network work is never performed inside the UnitOfWork transaction.

A disabled account is rejected before provider I/O. A missing account is rejected before provider I/O. If the platform or provider identity changes while a probe is in flight, the old snapshot is not persisted under the new identity.

### Snapshot -> observation truth

Only normalized formal facts are copied:

```text
observation_id   <- probe_id
account_id       <- PlatformAccount.account_id
status           <- LiveSnapshot.status
observed_at      <- LiveSnapshot.observed_at
source           <- LiveSnapshot.source
source_started_at<- LiveSnapshot.source_started_at
```

`UNKNOWN` remains `UNKNOWN`; it is never converted to OFFLINE. Provider room/title/page metadata is not allowed to override status and is not promoted into the canonical LiveObservation state record in this slice.

Unexpected adapter-contract identity mismatch is an application invariant failure, not a fabricated UNKNOWN/OFFLINE observation.

### Acceptance — Gate 1.4-2

Accepted entering baseline is 243 tests. Ten new contracts raise the expected complete Gate 1 suite to 253.

```text
A. Gate 1.4-1 PASS / CLOSED                         PASS
B. MonitoringProbeRequest contract                 PASS / CODE
C. provider I/O outside UnitOfWork                 PASS / CODE
D. stable probe_id -> observation_id               PASS / CONTRACT
E. existing logical probe reused before provider   PASS / CONTRACT
F. post-provider durable re-check                  PASS / CONTRACT
G. LiveSnapshot identity validated                 PASS / CONTRACT
H. UNKNOWN preserved as UNKNOWN                    PASS / CONTRACT
I. no LiveSession/LiveEvent/notification ownership PASS / CONTRACT
J. dedicated Gate 1.4-2 contracts                  PENDING / 10
K. complete Gate 1 suite                           PENDING / expected 253
```

Gate 1.4-2 remains CURRENT until J-K pass.

## 5. Next slices

Gate 1.4-3 will add scheduler cadence, bounded concurrency, retry/backoff, and one-logical-probe single-flight behavior. Gate 1.4-4 will then wire the accepted four-platform registry into the worker composition root. Gate 1.4-5 will validate durable observation behavior across restart/crash boundaries before Gate 1.4 closes.

## 6. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy/null eligibility guessed as enabled
follow or notification preference used as monitoring eligibility truth
provider failure converted to OFFLINE
provider I/O inside DB transaction
scheduler retry generating a new logical observation for the same probe_id
concurrent duplicate-probe risk ignored at Gate 1.4 exit
provider metadata used to override explicit LiveSnapshot.status
snapshot identity mismatch persisted under another account
Gate 1.4 creating LiveSession / LiveEvent
Gate 1.4 deciding notification eligibility
formal runtime importing legacy platform_adapters or experiments
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 must preserve that status rather than fabricating historical lifecycle evidence.
