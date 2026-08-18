# Gate 1.0-3 — Legacy Quarantine + Gate 1.1 Entry Freeze

Status: **PASS**

This document completes Gate 1.0 by freezing which legacy code may be reused, which code is reference-only, which code is quarantined from new formal runtime paths, and the exact entry conditions for Gate 1.1.

## 1. Quarantine principle

Gate 1 formal engineering must preserve accepted Gate 0 semantics even when legacy formal code predates them.

Therefore:

```text
legacy location != semantic authority
formal-looking file != accepted truth
Gate 0 accepted behavior > old V0.x docs/code
```

Existing legacy files are not deleted in Gate 1.0. They remain available for comparison, migration, and regression evidence, but they must not be extended in ways that preserve disproved semantics.

## 2. Legacy classification

### A. KEEP + MIGRATE SEMANTICS

These contain useful implementation or product behavior but must be mapped into the new formal ownership model:

```text
core/models.py
api/*
workers/*
platform_adapters/*
migrations/*
miniapp/*
```

Rule:
- keep files in place while Gate 1.1+ migrates behavior
- do not treat old enums/table shapes as authority
- new domain semantics enter through `stage_letter/*`
- existing API/worker entrypoints may delegate to new application services once available

### B. REFERENCE-ONLY

These remain valuable as historical implementation evidence but must not be copied wholesale:

```text
core/live_session_engine.py
core/live_state.py
core/state_machine.py
workers/notify/*
workers/probe/*
legacy adapter status classification
legacy notification grant counters
```

Rule:
- behavior may be compared
- tests may be adapted if they do not encode stale semantics
- stale status/event/delivery assumptions must not be preserved

### C. TEST / ORACLE AUTHORITY

Accepted Gate 0 experiment modules are the semantic reference for Gate 1 migration:

```text
experiments/gate0b/state_engine.py
experiments/gate0b/sqlite_store.py
experiments/gate0b/test_state_engine.py
experiments/gate0b/test_sqlite_store.py

experiments/gate0c/source_composition.py
experiments/gate0c/platform_health.py
experiments/gate0c/poll_policy.py
experiments/gate0c/test_source_composition.py
experiments/gate0c/test_platform_health.py

experiments/gate0d/notification_truth.py
experiments/gate0d/provider_result.py
experiments/gate0d/delivery_retry.py
experiments/gate0d/test_notification_truth.py
experiments/gate0d/test_provider_result.py
experiments/gate0d/test_delivery_retry.py

experiments/gate0e/golden_path.py
experiments/gate0e/test_golden_path.py
```

Rule:
- these may define expected behavior
- formal runtime must never import them
- regression tests may compare formal results against them

### D. NEVER COPY FORWARD

The following semantics are quarantined regardless of source location:

```text
ONLINE as the new canonical replacement for accepted LIVE naming when it changes semantics
NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR as canonical creator live state
SUSPECT_ONLINE / SUSPECT_OFFLINE as persisted canonical creator truth
CONFIRMED_ONLINE as a substitute for LIVE_STARTED + cause
UNKNOWN -> OFFLINE coercion
missing field -> OFFLINE
provider failure -> OFFLINE
notification failure -> OFFLINE
adapter directly opening/closing LiveSession
adapter directly emitting canonical LiveEvent
session-based notification delivery uniqueness
blind resend after unresolved external send
PENDING/SENT/FAILED-only delivery lifecycle
SENT -> global grant exhaustion inference
admin disabled == runtime source UNAVAILABLE
invented source_started_at / historical observation / event cause
raw AppSecret/access_token/session_key/login-code persisted
```

## 3. Legacy persistence rules

Gate 1.1 may add new tables/columns/indexes but must preserve current committed Alembic history.

Required forward-only strategy:

```text
EXPAND
  -> deterministic BACKFILL
  -> VERIFY
  -> CONTRACT later
```

Gate 1.1 must not:
- edit old migration files
- drop legacy tables/columns
- rewrite historical rows into invented truth
- synthesize LiveObservation rows when no observation evidence exists
- infer BOOTSTRAP vs TRANSITION when legacy data cannot prove it

## 4. Formal ownership boundary

New semantic authority starts under:

```text
stage_letter/domain/
stage_letter/application/
stage_letter/infrastructure/
```

Allowed dependency direction:

```text
api/workers -> application -> domain
                    ^
                    |
              infrastructure
```

Forbidden:

```text
domain -> SQLAlchemy/FastAPI/Redis/Dramatiq/HTTP provider
formal runtime -> experiments/*
adapter -> persistence state mutation
provider result -> creator live truth mutation
```

## 5. Gate 1.1 entry criteria

Gate 1.1 may begin only if all conditions below are true.

### E1 — semantic authority frozen

PASS when:
- Gate 0B/0C/0D/0E invariants are explicitly documented
- Gate 0A remains DEGRADED with known lifecycle evidence gap
- no unresolved conflict exists between formal target semantics and accepted Gate 0 truth

### E2 — domain ownership frozen

PASS when:
- 10 V0.1 domain entities are frozen
- Creator != PlatformAccount
- Follow != NotificationPreference
- LiveObservation is first-class durable evidence

### E3 — persistence direction frozen

PASS when:
- forward-only Alembic migration strategy is fixed
- old migrations remain immutable
- additive-first schema evolution is required
- no fabricated historical truth is allowed

### E4 — reuse/quarantine boundary frozen

PASS when:
- Gate 0 experiment reuse map exists
- legacy no-copy semantic list exists
- formal runtime imports from experiments are forbidden

### E5 — implementation order frozen

Gate 1.1 executes only in this order:

```text
1. pure domain types + invariants
2. formal semantic unit tests
3. repository/application ports
4. SQLAlchemy persistence model
5. Alembic expand migration
6. deterministic backfill
7. DB constraints/indexes
8. clean-db migration test
9. legacy-upgrade migration test
10. Gate 0 regression oracle comparison
```

### E6 — stop conditions frozen

Gate 1.1 must stop as FAIL/BLOCKED if any implementation requires:

```text
inventing past observations
inventing source start time
inventing event cause
coercing UNKNOWN to OFFLINE
changing accepted notification idempotency
blind retry after AMBIGUOUS
changing Gate 0 accepted event/session behavior
```

## 6. Gate 1.1 minimum test gates

Before Gate 1.1 can PASS, the formal implementation must prove at minimum:

```text
T1 UNKNOWN never closes an open session
T2 duplicate observation is idempotent
T3 stale observation cannot mutate canonical truth
T4 first repeated LIVE may create BOOTSTRAP_LIVE without notification eligibility
T5 OFFLINE -> confirmed LIVE creates one TRANSITION LIVE_STARTED
T6 one PlatformAccount cannot have >1 open LiveSession
T7 logical NotificationDelivery unique by (user_id, live_event_id, channel)
T8 IN_FLIGHT is durable before external send
T9 unresolved restored IN_FLIGHT becomes AMBIGUOUS
T10 AMBIGUOUS does not blind resend
T11 SENT does not infer global grant exhaustion
T12 notification/provider failure cannot mutate creator live truth
T13 clean database migrates to head
T14 representative legacy database migrates to head without fabricated truth
T15 Gate 0E golden-path behavior remains equivalent at the formal boundary
```

## 7. Gate 1.0 final decision

Acceptance matrix:

```text
1. Gate 0 invariants recorded                     PASS
2. ten-domain-entity model frozen                 PASS
3. legacy drift matrix complete                   PASS
4. formal module ownership frozen                 PASS
5. PostgreSQL migration strategy frozen           PASS
6. experiment-to-formal reuse map frozen          PASS
7. legacy quarantine / no-copy list frozen        PASS
8. Gate 1.1 implementation entry acceptance       PASS
```

Final state:

```text
Gate 1.0-1  PASS
Gate 1.0-2  PASS
Gate 1.0-3  PASS
Gate 1.0    PASS
Gate 1.1    READY / NOT STARTED
```

Gate 0A remains `DEGRADED / progression allowed with known lifecycle evidence gap`; Gate 1.0 does not upgrade it to PASS.
