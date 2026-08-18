# Gate 1.0-2 — Formal Architecture & Migration Freeze

Status: **PASS / ARCHITECTURE FREEZE**

Date: 2026-08-18

This document freezes the formal Stage Letter V0.1 module ownership, persistence migration strategy, and Gate 0 experiment-to-formal reuse map. It does not migrate production logic yet.

## 1. Architecture decision

Formal engineering will use a new Python package as the semantic core while keeping API, workers, and miniapp as delivery/entrypoint layers.

```text
stage-letter/
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
      source_composition/
        composer.py
      queue/
      wechat/
        provider.py

  api/                 # FastAPI delivery/composition layer
  workers/             # probe/notify process entrypoints
  migrations/          # Alembic history remains top-level
  miniapp/             # WeChat client remains independent of Python package
  experiments/         # accepted Gate 0 evidence/oracles, not runtime imports
```

### Ownership rules

```text
domain
  owns pure business types, invariants, state transitions, event/delivery identity
  must not import FastAPI, SQLAlchemy, Redis, Dramatiq, requests/httpx, or WeChat SDK code

application
  orchestrates use-cases and repository/provider ports
  may depend on domain
  must not contain provider-specific truth rules

infrastructure
  implements PostgreSQL, source adapters, source composition, queue, provider boundaries
  may depend on domain/application ports

api / workers
  are composition roots and transport/process entrypoints
  must not own domain truth

miniapp
  consumes API contracts only
  never receives provider secrets

experiments
  remain regression evidence/oracles
  formal runtime must not import experiments/*
```

Dependency direction is frozen as:

```text
api/workers -> application -> domain
                    ^
                    |
              infrastructure
              implements ports
```

No reverse import from domain into infrastructure/application/entrypoints is allowed.

## 2. Frozen domain vocabulary

The formal V0.1 domain is exactly:

```text
User
Creator
CreatorProfile
PlatformAccount
Follow
NotificationPreference
LiveObservation
LiveSession
LiveEvent
NotificationDelivery
```

Supporting operational records may exist, including provider-grant bookkeeping, source health, queue/job state and telemetry, but they are not substitutes for these ten entities.

Key boundaries remain:

```text
Creator != PlatformAccount
one Creator -> N PlatformAccount
Follow != NotificationPreference
LiveObservation is durable evidence
Adapter/source fact != canonical live truth mutation
notification/provider result != creator live truth
```

## 3. Canonical live truth model

At the canonical adapter/composition/state-engine boundary:

```text
LIVE
OFFLINE
UNKNOWN
```

Detailed source diagnostics such as rate limiting, blocking, parse errors, timeout, auth/captcha and missing fields belong to source provenance / health / diagnostics.

They must not be represented as fake canonical OFFLINE states.

```text
UNKNOWN != OFFLINE
```

Administrative `is_disabled` also remains separate from observed runtime health.

Accepted runtime health states:

```text
STARTING
HEALTHY
DEGRADED
UNAVAILABLE
```

## 4. Formal event/session model

LiveObservation drives the state engine. Only the state engine owns LiveSession and LiveEvent mutation.

Formal event semantics must preserve type and cause separately.

Minimum V0.1 event vocabulary:

```text
LIVE_STARTED
LIVE_ENDED
```

Minimum start cause vocabulary:

```text
TRANSITION
BOOTSTRAP
```

Frozen notification boundary:

```text
LIVE_STARTED + TRANSITION -> may be notification-eligible
LIVE_STARTED + BOOTSTRAP  -> never notify
```

One PlatformAccount may have at most one open LiveSession. This invariant must exist in both domain tests and PostgreSQL partial uniqueness.

Duplicate observation IDs and stale facts must be idempotent/no-op with respect to current canonical truth.

## 5. Notification model freeze

Logical NotificationDelivery identity is:

```text
(user_id, live_event_id, channel)
```

Not session-based.

Minimum persisted delivery runtime states:

```text
PENDING
IN_FLIGHT
WAITING_RETRY
WAITING_AUTH
BLOCKED_CONFIG
SENT
FAILED_TERMINAL
AMBIGUOUS
```

Rules:

```text
IN_FLIGHT must be persisted before external send
SENT is terminal for that logical delivery
SENT does not prove global grant exhaustion
crash-after-send/before-response -> AMBIGUOUS
AMBIGUOUS -> no blind resend
unknown/non-zero provider code -> conservative mapping until evidence-backed
same provider payload is not an idempotency guarantee
```

Provider/grant bookkeeping is supporting infrastructure. It cannot mutate live truth and cannot infer global exhaustion from a successful send alone.

## 6. PostgreSQL target persistence model

Gate 1.1 will implement the ten domain entities with supporting operational tables. Exact SQL names may use plural snake_case, but semantic ownership is frozen.

Target domain persistence:

```text
users
creators
creator_profiles
platform_accounts
follows
notification_preferences
live_observations
live_sessions
live_events
notification_deliveries
```

Supporting persistence allowed:

```text
provider_grants / provider_authorizations
notification_jobs or queue bookkeeping
platform/source health
probe/source telemetry
```

### Required database constraints

```text
platform_accounts: unique(platform, platform_user_id)
follows: unique(user_id, platform_account_id) for V0.1 follow target semantics
notification_preferences: one preference record per follow/channel policy boundary
live_observations: stable observation identity unique per account/source observation
live_sessions: partial unique open session per platform_account
notification_deliveries: unique(user_id, live_event_id, channel)
```

LiveEvent and LiveObservation evidence are append-oriented; application code must not rewrite history merely to make current state look cleaner.

## 7. Migration strategy — EXPAND / BACKFILL / VERIFY / CONTRACT

The existing Alembic chain remains immutable historical baseline. Gate 1 must not rewrite the current three committed migration files.

Current baseline chain contains:

```text
5354a9ed7741_initial_schema_11_tables.py
c23b5e229894_add_notification_jobs_attempt_and_next_.py
e98c1011d830_add_live_sessions_started_at_source.py
```

Gate 1.1 creates new forward-only migrations after the existing head.

### Phase A — Expand

Add new tables/columns/indexes without dropping legacy data:

```text
creators / creator_profiles as required by final mapping
follows
notification_preferences
live_observations
new LiveEvent type/cause columns or replacement representation
new NotificationDelivery live_event_id + accepted runtime state fields
runtime source-health representation
```

Legacy columns/tables remain readable during migration.

### Phase B — Backfill

Backfill only facts that can be derived without inventing provenance.

Allowed examples:

```text
legacy anchor identity -> Creator when mapping is direct and deterministic
legacy user_subscription relationship -> Follow
legacy notification settings -> NotificationPreference
existing session/event foreign keys -> new event-based delivery relationship only when exact event identity is derivable
```

Forbidden backfill:

```text
invented LiveObservation rows for historical probes that were never persisted
invented source_started_at
assuming UNKNOWN was OFFLINE
inventing event cause when bootstrap vs transition is unknowable
inventing provider/grant truth
```

Unknown historical truth remains unknown/null or explicitly legacy-unclassified.

### Phase C — Verify

Before any legacy removal:

```text
schema constraints pass
Gate 0B state-engine regression oracle passes
Gate 0C source-composition/health oracle passes
Gate 0D notification/delivery oracle passes
Gate 0E golden-path oracle passes
migration upgrade from clean baseline passes
migration upgrade from representative legacy dataset passes
restart/idempotency tests pass
```

### Phase D — Contract

No destructive rename/drop is allowed in Gate 1.1.

Legacy tables/columns may be contracted only in a later explicitly accepted gate after:

```text
all reads/writes moved to new model
backfill verified
rollback/backup plan exists
no production data provenance is lost
```

Because current deployment/data state is not assumed, Gate 1.1 defaults to additive compatibility rather than destructive cleanup.

## 8. Experiment -> formal reuse map

Accepted Gate 0 code is reused by semantic extraction, not copied blindly and not imported at runtime from `experiments/`.

```text
experiments/gate0b/state_engine.py
  -> stage_letter/domain/live.py + application/live_state_service.py
  reuse level: HIGH
  rule: preserve transition/idempotency/watermark/bootstrap semantics and tests

experiments/gate0b/sqlite_store.py
  -> infrastructure/db/repositories + transaction/restart tests
  reuse level: BEHAVIORAL REFERENCE
  rule: PostgreSQL replaces SQLite, atomicity/restart semantics remain

experiments/gate0c/source_composition.py
  -> infrastructure/source_composition/composer.py
  reuse level: HIGH
  rule: preserve source roles, conflict->UNKNOWN, metadata provenance separation

experiments/gate0c/platform_health.py
  -> domain/health.py + infrastructure health persistence
  reuse level: HIGH
  rule: preserve STARTING/HEALTHY/DEGRADED/UNAVAILABLE; admin disabled stays separate

experiments/gate0c/poll_policy.py
  -> workers/probe scheduling policy
  reuse level: POLICY REFERENCE
  rule: scheduler may change infrastructure, health/backoff meaning must not

experiments/gate0d/notification_truth.py
  -> domain/notifications.py + application/notification_service.py
  reuse level: HIGH
  rule: preserve eligibility and event-based logical delivery identity

experiments/gate0d/provider_result.py
  -> infrastructure/wechat/provider.py normalization boundary
  reuse level: HIGH
  rule: no speculative provider-code mapping

experiments/gate0d/delivery_retry.py
  -> domain/notifications.py delivery runtime + persistent application orchestration
  reuse level: HIGH
  rule: preserve durable IN_FLIGHT, AMBIGUOUS, no-blind-retry semantics

experiments/gate0d/real_wechat_probe.py
  -> provider integration test/support only
  reuse level: TEST REFERENCE
  rule: never migrate credential capture/prompt logic into domain

experiments/gate0e/golden_path.py
experiments/gate0e/test_golden_path.py
  -> Gate 1 cross-layer regression/acceptance oracle
  reuse level: ORACLE
  rule: formal path must reproduce accepted semantics without importing experiment modules at runtime
```

The repository confirms the accepted Gate 0B implementation contains `state_engine.py` and `sqlite_store.py`; Gate 0C contains `source_composition.py`, `platform_health.py`, and poll-policy/fault tests; Gate 0D contains the notification truth/provider/retry modules; Gate 0E contains the golden-path harness and tests.

## 9. Legacy files: migration disposition

Current top-level formal code is not deleted in Gate 1.0.

```text
core/models.py
  disposition: REPLACE SEMANTICS IN NEW INFRASTRUCTURE MODEL
  reason: stale status/event/delivery/grant boundaries

core/live_state.py
core/live_session_engine.py
core/state_machine.py
  disposition: QUARANTINE / COMPARE AGAINST GATE 0B
  reason: old state vocabulary must not become authority

workers/notify/*
  disposition: ENTRYPOINT/INFRASTRUCTURE CANDIDATE ONLY
  reason: retry/eligibility truth must come from accepted Gate 0D semantics

platform_adapters/*
  disposition: TRANSPORT PARSER CANDIDATE
  reason: useful platform parsing may survive, status contract must be normalized

api/*
  disposition: DELIVERY LAYER CANDIDATE
  reason: API endpoints may be adapted after application ports are frozen

miniapp/*
  disposition: CLIENT CANDIDATE
  reason: preserve UI work, rebind to Gate 1 API truth later
```

## 10. Explicit no-copy-forward list

The following legacy semantics must not be copied into new formal modules:

```text
ONLINE / NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR as canonical creator status
SUSPECT_ONLINE / SUSPECT_OFFLINE as persisted canonical truth vocabulary
CONFIRMED_ONLINE as a substitute for LIVE_STARTED + cause
notification delivery identity based on live_session_id
PENDING/SENT/FAILED-only delivery runtime
blind retry after uncertain external send
SENT -> infer global grant exhausted
provider/notification failure -> mutate creator OFFLINE
missing field / timeout / parse failure -> OFFLINE
administrative disabled == runtime UNAVAILABLE
adapter directly creating/closing LiveSession or LiveEvent
runtime imports from experiments/*
raw AppSecret/access_token/session_key/login code/openid persisted as evidence
```

## 11. Gate 1.1 executable entry plan

Gate 1.1 is **Domain Model + PostgreSQL Schema** and must proceed in this order:

```text
1. create stage_letter/domain pure types and invariants
2. port Gate 0B/0D semantic tests to formal domain tests
3. define repository/application ports
4. implement new SQLAlchemy persistence models
5. add forward-only Alembic expand migration
6. implement deterministic legacy backfill where safe
7. add PostgreSQL constraints for open session and logical delivery identity
8. run clean-database migration test
9. run representative legacy-upgrade migration test
10. run Gate 0B/0C/0D/0E regression oracles against formal boundaries
```

Gate 1.1 must stop with FAIL/BLOCKED if migration requires invented historical truth or if any accepted Gate 0 invariant changes.

## 12. Gate 1.0-2 acceptance

```text
D. target module/package boundary documented                  PASS
E. PostgreSQL persistence + forward migration strategy       PASS
F. experiment implementation -> formal module reuse map      PASS
```

Gate 1.0 remains CURRENT because legacy quarantine/no-copy disposition and final Gate 1.1 entry acceptance still need one final closure review in Gate 1.0-3.

Next: **Gate 1.0-3 — Legacy Quarantine + Gate 1.1 Entry Freeze**.
