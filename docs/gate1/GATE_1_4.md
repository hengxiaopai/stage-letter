# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **CURRENT / 1.4-1 MONITORING TARGET DISCOVERY LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.4-1  Monitoring Target Discovery + Paging Contract        CURRENT
Gate 1.4-2  Probe Request + LiveSnapshot -> LiveObservation      NOT STARTED
Gate 1.4-3  Scheduler Cadence / Concurrency / Backoff            NOT STARTED
Gate 1.4-4  Worker Composition + Four-platform Runtime Wiring    NOT STARTED
Gate 1.4-5  Observation Durability / Restart Acceptance          NOT STARTED
```

## 3. Gate 1.4-1 — landed

Landed runtime:

```text
stage_letter/application/services/monitoring.py
stage_letter/application/ports.py
stage_letter/infrastructure/db/repositories/creator.py
stage_letter/application/services/__init__.py
workers/composition.py
```

Landed contracts:

```text
tests/gate1/test_gate14_monitoring_targets.py  8 tests
```

Existing contract suites were also updated to include the new repository/service seam without increasing their test count.

### Target-selection truth

Only explicitly enabled formal accounts are eligible:

```text
platform_accounts.is_disabled = false -> eligible monitoring target
platform_accounts.is_disabled = true  -> excluded
platform_accounts.is_disabled = null  -> not silently promoted to enabled
```

This is intentionally conservative for legacy bridge rows. Gate 1.4 does not infer monitoring eligibility from follow rows, notification preferences, room metadata, or provider availability.

### Stable paging

Target discovery is keyset-paged by canonical account id:

```text
ORDER BY platform_accounts.id ASC
WHERE id > after_account_id   # when cursor supplied
LIMIT 1..1000
```

Default page size is 100. Hard cap is 1000. Invalid page sizes fail before opening a UnitOfWork.

### Transaction and provider boundary

`MonitoringTargetApplicationService.list_targets()` is read-only. It opens a formal UnitOfWork only for target discovery and does not call `commit()`.

No provider request, adapter lookup, scheduler sleep, session/event mutation, or notification logic is allowed in 1.4-1. Worker composition merely exposes the service; constructing the worker bundle does not open a DB session or provider connection.

## 4. Accepted entering baseline

Gate 1.3 closed with:

```text
10 / 10 Gate 1.3 final acceptance contracts PASS
235 / 235 complete Gate 1 suite              PASS
```

Gate 1.4-1 adds 8 new deterministic tests. Expected local evidence is therefore:

```text
8 / 8 Gate 1.4 monitoring-target contracts
243 / 243 complete Gate 1 suite
```

These are user-local deterministic tests, not a CI or provider-network claim.

## 5. Acceptance — Gate 1.4-1

```text
A. Gate 1.3 PASS / CLOSED                         PASS
B. monitoring target application service          PASS / CODE
C. CreatorRepository enabled-target port           PASS / CODE
D. SQLAlchemy explicit-enabled keyset paging       PASS / CODE
E. legacy NULL is_disabled not auto-enabled        PASS / CONTRACT
F. target discovery performs no provider I/O       PASS / CONTRACT
G. worker composition exposes target service       PASS / CODE
H. dedicated Gate 1.4-1 contracts                  PENDING / 8
I. complete Gate 1 suite                           PENDING / expected 243
```

Gate 1.4-1 remains CURRENT until H-I pass.

## 6. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy/null eligibility guessed as enabled
follow or notification preference used as monitoring eligibility truth
provider failure converted to OFFLINE
scheduler/provider I/O inside target-discovery DB transaction
provider metadata used to override explicit LiveSnapshot.status
Gate 1.4 creating LiveSession / LiveEvent
Gate 1.4 deciding notification eligibility
formal runtime importing legacy platform_adapters or experiments
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 must preserve that status rather than fabricating historical lifecycle evidence.
