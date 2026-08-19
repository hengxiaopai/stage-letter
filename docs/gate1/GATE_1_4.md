# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **CURRENT / 1.4-1 PASS / 1.4-2 PASS / 1.4-3 PASS / CLOSED / 1.4-4 FOUR-PLATFORM WORKER WIRING LANDED / LOCAL EVIDENCE PENDING**

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

Gate 1.4 owns target discovery, scheduling/probe orchestration, worker composition, and observation ingestion only. It does not create/close LiveSession, emit LiveEvent, or decide notification eligibility.

## 2. Internal slices

```text
Gate 1.4-1  Monitoring Target Discovery + Paging Contract        PASS / CLOSED
Gate 1.4-2  Probe Request + LiveSnapshot -> LiveObservation      PASS / CLOSED
Gate 1.4-3  Scheduler Cadence / Concurrency / Backoff            PASS / CLOSED
Gate 1.4-4  Worker Composition + Four-platform Runtime Wiring    CURRENT
Gate 1.4-5  Observation Durability / Restart Acceptance          NOT STARTED
```

## 3. Gate 1.4-1 — PASS / CLOSED

Accepted user-local evidence:

```text
Gate 1.4 monitoring-target contracts   8 / 8 PASS
complete Gate 1 suite                243 / 243 PASS
```

Only explicitly enabled formal PlatformAccount rows are monitoring targets. Target discovery is keyset-paged by canonical account id, read-only, provider-free, and notification-independent.

## 4. Gate 1.4-2 — PASS / CLOSED

Accepted user-local evidence:

```text
probe -> observation contracts   10 / 10 PASS
complete Gate 1 suite           253 / 253 PASS
```

One logical request remains `probe_id + account_id`; retries reuse the same probe id and therefore the same durable observation id. Provider work remains outside UnitOfWork boundaries. `UNKNOWN` remains `UNKNOWN`, snapshot identity is validated, and room/title/page metadata does not override live state.

## 5. Gate 1.4-3 — PASS / CLOSED

Accepted user-local evidence:

```text
scheduler contracts          10 / 10 PASS
complete Gate 1 suite       263 / 263 PASS
```

Accepted scheduler mechanics:

```text
default cadence_seconds            30
default max_concurrency            16
default per_platform_concurrency    4
default max_attempts                3
default base_backoff_seconds        1
default max_backoff_seconds         8
default page_size                 100
```

For one `(cycle_id, account_id)` the scheduler derives one stable bounded logical probe id and all retries reuse that request. Same-process duplicate calls for the same `(account_id, probe_id)` share one in-flight task. Global and per-platform concurrency are separately bounded. Retry applies only to escaped `TimeoutError` / `ConnectionError`; a successfully normalized UNKNOWN observation is not retried merely because its status is UNKNOWN.

Gate 1.4-3 does **not** claim distributed exactly-once provider execution. Cross-process/restart durability remains Gate 1.4-5.

Result: **Gate 1.4-3 PASS / CLOSED**.

## 6. Gate 1.4-4 — CURRENT

### Landed runtime wiring

`workers/composition.py` now builds the complete formal monitoring runtime:

```text
SQLAlchemy UnitOfWork factory
  -> Creator / Follow / LiveObservation application services
  -> MonitoringTargetApplicationService
  -> formal four-platform AdapterRegistry
  -> MonitoringProbeApplicationService(registry.get)
  -> MonitoringScheduler(targets, probe)
```

The registry contains exactly:

```text
bilibili
douyin
douyu
huya
```

and continues to use only the Gate 1.3 formal adapters/gateways.

`build_worker_services()` accepts optional worker configuration only:

```text
douyin_cookie
scheduler_policy
```

These values configure infrastructure/runtime mechanics; they do not enter domain truth.

### Construction boundary

Building `WorkerServiceBundle` must remain side-effect free:

```text
no database session opened
no UnitOfWork entered
no provider request
no eager StreamGet import
no scheduler cycle started
```

The bundle owns one shared UoW factory for its formal application services and probe service. The MonitoringProbeApplicationService is bound to the exact AdapterRegistry carried by the same bundle. The MonitoringScheduler is bound to the exact target service and probe service carried by that bundle.

Every call to `build_worker_services()` returns fresh registry, adapter, probe, and scheduler instances; no hidden process-global mutable runtime is introduced.

### Landed deterministic contracts

```text
tests/gate1/test_gate14_worker_wiring.py  10 tests
```

The contracts verify:

```text
exact four-platform registry in worker bundle
all entries implement LivePlatformAdapter and key == adapter.platform
probe shares the worker UoW factory
probe adapter lookup is bound to the bundle registry
scheduler uses the same target/probe instances
custom scheduler policy is preserved
construction opens no DB session
construction does not eagerly import StreamGet
separate builds return fresh runtime instances
composition root owns wiring only, not live truth/session/event/notification rules
```

Accepted entering baseline is 263 tests. Ten new worker-wiring contracts raise the expected complete Gate 1 suite to 273.

### Acceptance — Gate 1.4-4

```text
A. Gate 1.4-3 PASS / CLOSED                         PASS
B. formal four-platform registry wired              PASS / CODE
C. target -> probe -> scheduler object graph         PASS / CODE
D. one shared formal UoW factory                     PASS / CONTRACT
E. worker construction performs no DB/provider I/O   PASS / CONTRACT
F. StreamGet remains lazy                            PASS / CONTRACT
G. no legacy runtime dependency                      PASS / CONTRACT
H. no live-state/session/event/notification ownership PASS / CONTRACT
I. dedicated Gate 1.4-4 contracts                    PENDING / 10
J. complete Gate 1 suite                             PENDING / expected 273
```

Gate 1.4-4 remains CURRENT until I-J pass.

## 7. Next slice

Gate 1.4-5 will validate durable observation behavior across restart/crash/concurrent-process boundaries. It must close the remaining logical-probe duplicate risk without claiming provider exactly-once semantics that the persistence model cannot prove.

## 8. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy/null eligibility guessed as enabled
follow or notification preference used as monitoring eligibility truth
provider failure converted to OFFLINE
provider I/O inside DB transaction
worker construction performing provider I/O or opening a DB session
scheduler retry generating a new logical observation id
UNKNOWN treated as scheduler failure merely because status is UNKNOWN
cross-process exactly-once claimed without evidence
provider metadata overriding LiveSnapshot.status
snapshot identity mismatch persisted under another account
Gate 1.4 creating LiveSession / LiveEvent
Gate 1.4 deciding notification eligibility
formal runtime importing legacy platform_adapters or experiments
```

## 9. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 must preserve that status rather than fabricate historical lifecycle evidence.
