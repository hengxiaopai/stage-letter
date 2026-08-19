# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **CURRENT / 1.4-1 PASS / 1.4-2 PASS / 1.4-3 PASS / 1.4-4 PASS / CLOSED / 1.4-5 DURABILITY LANDED / LOCAL+POSTGRES EVIDENCE PENDING**

Entry authority: Gate 1.3 PASS / CLOSED.

## 1. Goal

Gate 1.4 connects the accepted four-platform adapter framework to durable monitoring without allowing scheduler mechanics, provider failures, or weak metadata to rewrite canonical live truth.

```text
explicitly enabled PlatformAccount
  -> deterministic target discovery
  -> scheduler logical probe
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
Gate 1.4-4  Worker Composition + Four-platform Runtime Wiring    PASS / CLOSED
Gate 1.4-5  Observation Durability / Restart Acceptance          CURRENT
```

## 3. Accepted slices

```text
1.4-1  8 / 8 dedicated + 243 / 243 complete Gate 1 PASS
1.4-2 10 / 10 dedicated + 253 / 253 complete Gate 1 PASS
1.4-3 10 / 10 dedicated + 263 / 263 complete Gate 1 PASS
1.4-4 10 / 10 dedicated + 273 / 273 complete Gate 1 PASS
```

Gate 1.4-4 therefore closes with the formal four-platform registry, target service, probe service, and scheduler wired through one side-effect-free worker composition root. Construction opens no DB session, performs no provider request, and keeps StreamGet lazy.

## 4. Gate 1.4-5 — CURRENT

### 4.1 Remaining risk entering this slice

The historical `live_observations` uniqueness is:

```text
(platform_account_id, source, observation_id)
```

That remains valid legacy/provider evidence identity, but it is insufficient for one scheduler logical probe when two independent processes race and provider `source` differs. Same-process scheduler single-flight cannot close that cross-process persistence race.

Gate 1.4-5 therefore hardens **formal scheduler-generated observations only**. It does not rewrite legacy rows or claim provider exactly-once execution.

### 4.2 Formal monitoring probe namespace

Production monitoring requests are now required to use:

```text
monitor:<logical-id>
```

`make_probe_id(cycle_id, account_id)` already emits this namespace. `MonitoringProbeRequest` now rejects non-`monitor:` ids so the application cannot accidentally bypass the durable scheduler-probe identity contract.

### 4.3 Forward-only migration

Landed:

```text
migrations/versions/d14e7c9a5b30_gate14_monitor_probe_identity.py
```

New Alembic head:

```text
d14e7c9a5b30
```

The migration adds a partial unique index:

```text
uq_g14_monitor_probe_identity
  UNIQUE (platform_account_id, observation_id)
  WHERE observation_id LIKE 'monitor:%'
```

Before creating the index the migration checks for already-existing duplicate `monitor:*` rows. If any exist, migration stops explicitly. It does **not** delete, merge, update, or invent historical evidence.

Legacy/non-monitor observation ids keep the historical source-scoped uniqueness semantics.

### 4.4 Race-aware repository/application contract

`LiveRepository.append_observation()` now returns:

```text
True  -> this transaction inserted the durable row
False -> another/idempotent write already owns the durable identity
```

The SQLAlchemy repository uses PostgreSQL `ON CONFLICT DO NOTHING` without a single named conflict target and `RETURNING id`. This allows both the historical source-scoped constraint and the new formal monitor-probe partial unique index to protect the same insert path.

If a probe process loses the insert race, `MonitoringProbeApplicationService` re-reads `(account_id, observation_id)` and returns the durable winner with `reused_existing=True`. It does not commit a phantom local observation. If the database reports a conflict but no durable winner is readable, that is an explicit application invariant failure.

### 4.5 Restart / independent-session evidence probe

Landed:

```text
scripts/gate14_observation_durability_probe.py
```

The probe requires migration head `d14e7c9a5b30`, creates an isolated temporary formal account, then starts two independent SQLAlchemy sessions racing the same `monitor:*` probe id with different source/status values. Acceptance requires exactly one insert winner and one durable row. It then disposes/recreates the engine and verifies the same single row remains after the runtime restart boundary. Test rows are removed afterward.

This proves durable **observation identity**, not exactly-once provider execution. Two OS processes may both perform provider I/O before one loses the DB insert race; Gate 1.4 makes no stronger claim.

### 4.6 Landed deterministic contracts

```text
tests/gate1/test_gate14_durability.py  10 tests
```

The contracts cover migration lineage/predicate/preflight, ORM parity, repository insert-result semantics, conflict handling, mandatory `monitor:` namespace, race-loser winner reuse, impossible-conflict failure, scheduler id compatibility, restart-probe shape, and explicit no-provider-exactly-once claim.

Accepted entering baseline is 273 tests. Ten new tests raise the expected complete Gate 1 suite to:

```text
283 / 283
```

### 4.7 Acceptance — Gate 1.4-5

```text
A. Gate 1.4-4 PASS / CLOSED                              PASS
B. formal monitor-probe partial unique migration         PASS / CODE
C. migration refuses duplicate evidence rewrite          PASS / CONTRACT
D. repository insert winner/loser signal                 PASS / CODE
E. insert-race loser reloads durable winner              PASS / CONTRACT
F. scheduler-generated probe ids covered by DB predicate PASS / CONTRACT
G. dedicated Gate 1.4-5 contracts                        PENDING / 10
H. complete Gate 1 suite                                 PENDING / expected 283
I. Alembic upgrade to d14e7c9a5b30                      PENDING / LOCAL POSTGRES
J. independent-session race + engine-restart probe       PENDING / LOCAL POSTGRES
```

Gate 1.4 remains CURRENT until G-J pass.

## 5. Gate 1.4 exit condition

If deterministic tests, migration, and PostgreSQL durability evidence all pass:

```text
Gate 1.4-5  PASS / CLOSED
Gate 1.4    PASS / CLOSED
Gate 1.5    CURRENT
```

Gate 1.5 then owns canonical state/session/event persistence. Gate 1.4 must not create those outputs itself.

## 6. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy/null eligibility guessed as enabled
follow or notification preference used as monitoring eligibility truth
provider failure converted to OFFLINE
provider I/O inside DB transaction
migration deleting/merging ambiguous historical observation evidence
scheduler retry generating a new logical observation id
formal monitor request bypassing the monitor: durable namespace
UNKNOWN treated as failure merely because status is UNKNOWN
provider exactly-once claimed from a DB uniqueness guarantee
provider metadata overriding LiveSnapshot.status
Gate 1.4 creating LiveSession / LiveEvent
Gate 1.4 deciding notification eligibility
formal runtime importing legacy platform_adapters or experiments
```

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 must preserve that status rather than fabricate historical lifecycle evidence.
