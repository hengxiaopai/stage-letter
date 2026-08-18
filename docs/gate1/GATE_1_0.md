# Gate 1.0 — Formal Engineering Handoff

Status: **CURRENT / 1.0-2 ARCHITECTURE FREEZE PASS**

Baseline commit entering Gate 1: `c841a33d` (`chore: establish clean Stage Letter engineering baseline`).

Detailed architecture/migration freeze: [`GATE_1_0_ARCHITECTURE_FREEZE.md`](./GATE_1_0_ARCHITECTURE_FREEZE.md).

## 1. Purpose

Gate 1.0 is the boundary between Gate 0 experiments and formal V0.1 engineering. It does not add new product semantics. Accepted Gate 0 truth is the only authority used by the formal domain model, persistence layer, workers, API, and miniapp integration.

Canonical runtime path:

```text
Adapter / source
  -> SourceObservation
  -> SourceComposer
  -> canonical LiveObservation
  -> persistent State Engine
  -> LiveSession
  -> LiveEvent
  -> notification eligibility
  -> logical NotificationDelivery
  -> delivery runtime
  -> provider result
```

## 2. Frozen Gate 0 invariants

```text
UNKNOWN != OFFLINE
BOOTSTRAP_LIVE != TRANSITION
provider/notification failure != creator live truth
one PlatformAccount has at most one open LiveSession
duplicate observations must not duplicate sessions/events
stale observations must not mutate current canonical truth
logical NotificationDelivery identity = (user_id, live_event_id, channel)
provider SENT is terminal for that logical delivery
provider SENT does not prove global grant exhaustion
same provider payload may create duplicate external notifications
crash-after-send/before-response -> AMBIGUOUS
AMBIGUOUS -> no blind resend
non-zero provider codes remain conservative until evidence-backed
AppSecret/access_token/session_key/login-code/raw-openid must never be persisted
```

## 3. Frozen V0.1 domain entities

```text
1. User
2. Creator
3. CreatorProfile
4. PlatformAccount
5. Follow
6. NotificationPreference
7. LiveObservation
8. LiveSession
9. LiveEvent
10. NotificationDelivery
```

Boundaries:

```text
Creator != PlatformAccount
one Creator may own N PlatformAccounts
Follow != NotificationPreference
Adapter facts do not directly mutate canonical creator truth
LiveObservation is durable evidence
```

Supporting operational tables may exist for queues, health, telemetry, or provider bookkeeping, but must not replace or blur these ten entities.

## 4. Legacy drift matrix

The clean formal baseline predates accepted Gate 0B/0C/0D/0E semantics in several places.

```text
D1 canonical live status stale
   legacy: ONLINE/OFFLINE + transport/provider statuses + SUSPECT states
   target: LIVE/OFFLINE/UNKNOWN canonical truth; diagnostics separate

D2 durable LiveObservation missing
   target: first-class persisted evidence before state mutation

D3 Follow and NotificationPreference collapsed
   target: relationship truth and notification settings split

D4 event semantics stale
   legacy: SUSPECT/CONFIRMED event vocabulary
   target: LiveEvent type + cause; LIVE_STARTED/TRANSITION eligible, BOOTSTRAP not

D5 NotificationDelivery identity stale
   legacy: (user_id, live_session_id, channel)
   target: (user_id, live_event_id, channel)

D6 delivery runtime too coarse
   legacy: PENDING/SENT/FAILED
   target: PENDING/IN_FLIGHT/WAITING_RETRY/WAITING_AUTH/BLOCKED_CONFIG/
           SENT/FAILED_TERMINAL/AMBIGUOUS

D7 WeChat grant bookkeeping language stale
   target: SENT never implies global exhaustion without explicit provider evidence

D8 runtime health mixed with admin disabled
   target runtime: STARTING/HEALTHY/DEGRADED/UNAVAILABLE
   admin enable/disable remains separate

D9 adapter contract predates final source-composition boundary
   target LiveSnapshot.status: LIVE/OFFLINE/UNKNOWN only
```

Existing `core/models.py`, old state engines/workers, and old adapter enums remain legacy baseline until migrated; they are not authoritative merely because they are under formal directories.

## 5. Gate 1.0-2 architecture freeze — PASS

Formal semantic package ownership is frozen as:

```text
stage_letter/
  domain/
    creators.py
    follows.py
    live.py
    notifications.py
    health.py
  application/
    creator_service.py
    follow_service.py
    live_observation_service.py
    live_state_service.py
    notification_service.py
  infrastructure/
    db/
      models.py
      repositories/
    adapters/
      base.py
      douyin.py
      bilibili.py
      huya.py
      douyu.py
    source_composition/composer.py
    queue/
    wechat/provider.py

api/          # delivery/composition root
workers/      # process entrypoints
migrations/   # top-level Alembic history
miniapp/      # independent WeChat client
experiments/  # evidence/oracles; never runtime imports
```

Dependency direction:

```text
api/workers -> application -> domain
                    ^
                    |
              infrastructure implements ports
```

Domain cannot depend on FastAPI, SQLAlchemy, Redis, Dramatiq, HTTP clients, or WeChat SDK/provider code.

## 6. PostgreSQL migration strategy — FROZEN

Existing committed Alembic history remains immutable:

```text
5354a9ed7741_initial_schema_11_tables.py
c23b5e229894_add_notification_jobs_attempt_and_next_.py
e98c1011d830_add_live_sessions_started_at_source.py
```

Gate 1.1 uses forward-only:

```text
EXPAND -> BACKFILL -> VERIFY -> CONTRACT(later gate only)
```

Gate 1.1 is additive. It may add formal domain tables/columns/indexes and safe deterministic backfills; it must not destructively rewrite old migrations or drop legacy data.

Forbidden historical invention:

```text
no fabricated LiveObservation history
no fabricated source_started_at
no UNKNOWN -> OFFLINE conversion
no invented BOOTSTRAP vs TRANSITION cause
no invented provider/grant truth
```

Required database constraints include:

```text
unique(platform, platform_user_id)
one open LiveSession per PlatformAccount via partial unique constraint
stable unique LiveObservation identity
unique(user_id, live_event_id, channel) for NotificationDelivery
```

## 7. Experiment -> formal reuse map — FROZEN

```text
Gate 0B state_engine.py
  -> domain/live.py + application/live_state_service.py
  HIGH semantic reuse

Gate 0B sqlite_store.py
  -> PostgreSQL repository/transaction behavior reference
  behavioral reference only

Gate 0C source_composition.py
  -> infrastructure/source_composition/composer.py
  HIGH semantic reuse

Gate 0C platform_health.py
  -> domain/health.py + health persistence
  HIGH semantic reuse

Gate 0C poll_policy.py
  -> probe scheduling policy
  policy reference

Gate 0D notification_truth.py
  -> domain/notifications.py + notification service
  HIGH semantic reuse

Gate 0D provider_result.py
  -> infrastructure/wechat/provider.py normalization
  HIGH semantic reuse

Gate 0D delivery_retry.py
  -> durable delivery runtime
  HIGH semantic reuse

Gate 0D real_wechat_probe.py
  -> integration test/support reference only

Gate 0E golden_path.py + test_golden_path.py
  -> cross-layer regression/acceptance oracle
```

Formal runtime must not import from `experiments/*`.

## 8. No-copy-forward semantic list

The following must not enter new Gate 1 modules:

```text
provider error statuses as canonical live truth
SUSPECT_* as persisted canonical creator truth
CONFIRMED_ONLINE replacing LIVE_STARTED + cause
session-based NotificationDelivery idempotency
PENDING/SENT/FAILED-only delivery runtime
blind retry after uncertain send
SENT -> global grant exhausted inference
notification/provider failure -> creator OFFLINE
missing field / timeout / parse error -> OFFLINE
admin disabled == runtime UNAVAILABLE
adapter directly creating/closing LiveSession or LiveEvent
runtime imports from experiments/*
raw provider credentials persisted as evidence
```

## 9. Gate 1.1 executable plan

Gate 1.1 is **Domain Model + PostgreSQL Schema** and will execute in this order:

```text
1. create pure stage_letter/domain types/invariants
2. port Gate 0B/0D semantic tests to formal domain tests
3. freeze repository/application ports
4. implement new SQLAlchemy persistence models
5. add forward-only Alembic expand migration
6. perform deterministic legacy backfill only where truth is derivable
7. add DB constraints for open session and delivery identity
8. test clean-database migration
9. test representative legacy-dataset upgrade
10. run Gate 0B/0C/0D/0E regression oracles against formal boundaries
```

Gate 1.1 must stop with FAIL/BLOCKED if migration requires invented historical truth or changes an accepted Gate 0 invariant.

## 10. Gate 1.0 acceptance matrix

```text
1. Gate 0B/0C/0D/0E truths recorded as formal invariants          PASS
2. ten-domain-entity model frozen                                 PASS
3. legacy-vs-accepted drift matrix complete                       PASS
4. formal module ownership frozen                                 PASS
5. PostgreSQL migration strategy frozen                           PASS
6. experiment-to-formal reuse map frozen                          PASS
7. legacy quarantine / no-copy list frozen                        CURRENT
8. Gate 1.1 implementation entry acceptance                       CURRENT
```

Gate 1.0 remains **CURRENT** until 1.0-3 performs the final quarantine/entry review and closes items 7-8.

## 11. Current progression

```text
Gate 0A    DEGRADED / inherited known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E    PASS
Git baseline c841a33d PASS

Gate 1.0-1  PASS / handoff + drift audit
Gate 1.0-2  PASS / architecture + migration + reuse freeze
Gate 1.0-3  NEXT / legacy quarantine + Gate 1.1 entry freeze
Gate 1.0    CURRENT
Gate 1.1    NOT STARTED
```

Gate 0A's deferred real lifecycle evidence gap remains visible and is not upgraded to PASS.
