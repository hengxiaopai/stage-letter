# Gate 1.0 — Formal Engineering Handoff

Status: **CURRENT / HANDOFF AUDIT IN PROGRESS**

Baseline commit entering Gate 1: `c841a33d` (`chore: establish clean Stage Letter engineering baseline`).

## 1. Purpose

Gate 1.0 is the boundary between Gate 0 experiments and formal V0.1 engineering.

It does **not** add new product semantics. Its job is to ensure that accepted Gate 0 truth is the only source of truth used by the formal domain model, persistence layer, workers, API, and miniapp integration.

Canonical V0.1 runtime path remains:

```text
Adapter / source
  -> SourceObservation
  -> Gate 0C SourceComposer
  -> canonical LiveObservation
  -> persistent State Engine
  -> LiveSession
  -> LiveEvent
  -> notification eligibility
  -> logical NotificationDelivery
  -> delivery runtime
  -> provider result
```

## 2. Gate 0 truths that are frozen into Gate 1

The following are non-negotiable engineering invariants:

```text
UNKNOWN != OFFLINE
BOOTSTRAP_LIVE != TRANSITION
provider/notification failure != creator live truth
one platform account has at most one open LiveSession
repeated/duplicate observations must not duplicate sessions/events
a stale observation must not mutate current canonical live truth
same logical NotificationDelivery is locally idempotent
logical delivery identity = (user_id, live_event_id, channel)
provider SENT is terminal for that logical delivery
provider SENT does not prove global grant exhaustion
exact same provider payload may create duplicate external notifications
crash-after-send/before-response -> AMBIGUOUS
AMBIGUOUS must never blind-resend
non-zero provider codes remain conservative until evidence-backed mapping exists
AppSecret/access_token/session_key/login-code/raw-openid must never be persisted
```

## 3. Frozen V0.1 domain entities

Gate 1 formal engineering targets these ten domain entities:

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

Important boundaries:

```text
Creator != PlatformAccount
one Creator may own N PlatformAccounts
Follow != NotificationPreference
Adapter facts do not directly mutate canonical creator truth
LiveObservation is durable evidence, not an implementation detail
```

Supporting operational tables may exist for queues, health, telemetry, or provider bookkeeping, but they must not replace or blur these domain boundaries.

## 4. Baseline audit — formal code/doc drift found

Gate 1.0 starts with a deliberate mismatch audit. The current formal baseline predates the accepted Gate 0B/0C/0D/0E semantics in several places.

### D1 — canonical live status model is stale

Current formal ORM still exposes the older seven-state/platform-state model plus `SUSPECT_ONLINE` / `SUSPECT_OFFLINE` in `PlatformAccount.last_status`.

Gate 0 accepted boundary is:

```text
LiveSnapshot / LiveObservation status = LIVE | OFFLINE | UNKNOWN
```

Provider failure classes and health diagnostics may remain detailed internally, but they must not masquerade as canonical creator live states.

**Required Gate 1 action:** separate source/provider diagnostics from canonical live truth.

### D2 — durable LiveObservation is missing from the formal ORM

Gate 0B/0C/0E depend on durable observations as the evidence boundary before state mutation.

The current formal 11-table ORM has `probe_runs`, but no domain `LiveObservation` model equivalent to the accepted state-engine input and source-composition evidence.

**Required Gate 1 action:** add a first-class durable `LiveObservation` persistence model with observation identity, status, observed time, source/provenance, and trusted source start time when available.

### D3 — Follow and NotificationPreference are currently collapsed

Current `user_subscriptions` contains both relationship truth and notification settings (`notify_enabled`, starred/silence fields).

Accepted domain boundary is:

```text
Follow != NotificationPreference
```

**Required Gate 1 action:** split relationship persistence from notification preference persistence without changing V0.1 user behavior.

### D4 — event semantics are stale

Current formal ORM event types are still the earlier `SUSPECT_ONLINE / CONFIRMED_ONLINE / SUSPECT_OFFLINE / CONFIRMED_OFFLINE` model.

Gate 0B/0E accepted event truth distinguishes event type and cause, including the crucial boundary:

```text
LIVE_STARTED + TRANSITION -> notification eligible
LIVE_STARTED + BOOTSTRAP -> never notify
```

**Required Gate 1 action:** formalize accepted `LiveEvent` type/cause semantics and preserve bootstrap origin.

### D5 — NotificationDelivery identity is incorrect for accepted Gate 0D semantics

Current ORM unique key is effectively:

```text
(user_id, live_session_id, channel)
```

Gate 0D froze logical delivery identity as:

```text
(user_id, live_event_id, channel)
```

**Required Gate 1 action:** migrate delivery identity to event-based idempotency.

### D6 — delivery runtime states are too coarse

Current formal delivery state is `PENDING / SENT / FAILED`.

Accepted Gate 0D retry machine requires at least:

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

Most importantly, `IN_FLIGHT` must be durable before external send and restored unresolved in-flight work must become `AMBIGUOUS`, not retry automatically.

**Required Gate 1 action:** persist the accepted delivery state machine rather than reimplementing a simplified retry loop.

### D7 — WeChat grant bookkeeping language is stale

Current baseline describes `granted_count / consumed_count` as an available-count ledger and older documentation contains assumptions about grant exhaustion.

Gate 0D real-provider evidence corrected the semantics:

```text
SENT -> terminal for the delivery
SENT -> one send entitlement was used
SENT does NOT prove global grant exhaustion
only explicit provider evidence may mark grant state EXHAUSTED
```

**Required Gate 1 action:** keep provider/grant bookkeeping conservative and ensure it cannot alter creator live truth or infer exhaustion from `SENT` alone.

### D8 — platform health enum differs from accepted Gate 0C

Current formal health states are `HEALTHY / DEGRADED / DISABLED`.

Accepted Gate 0C source-health model uses:

```text
STARTING / HEALTHY / DEGRADED / UNAVAILABLE
```

Operational `disabled` configuration may still exist, but it is not the same fact as runtime source health.

**Required Gate 1 action:** separate administrative enable/disable from observed runtime health.

### D9 — adapter contract must be normalized to the accepted boundary

Formal legacy adapters and specs predate the final Gate 0A/0C source-composition contract.

Gate 1 adapter-facing contract must preserve the accepted rule:

```ts
interface LivePlatformAdapter {
  resolveCreator(input: string): Promise<ResolvedCreator>;
  getCreatorProfile(account: PlatformAccount): Promise<CreatorProfileSnapshot>;
  getLiveSnapshot(account: PlatformAccount): Promise<LiveSnapshot>;
}
```

`LiveSnapshot.status` at the canonical adapter boundary is only `LIVE | OFFLINE | UNKNOWN`.

**Required Gate 1 action:** detailed transport/provider errors belong in provenance/diagnostics, not as fake OFFLINE truth.

## 5. What Gate 1.0 must produce

Gate 1.0 closes only when all of the following are available and consistent:

```text
A. Gate 0 -> Gate 1 semantic handoff document                    CURRENT
B. formal domain vocabulary frozen                               CURRENT
C. drift matrix between legacy baseline and accepted semantics    CURRENT
D. target module/package boundary documented                      PENDING
E. target persistence model and migration strategy documented     PENDING
F. reuse map: experiment implementation -> formal module           PENDING
G. explicit list of legacy code that must not be copied forward   PENDING
H. Gate 1.1 entry criteria                                         PENDING
```

## 6. Proposed formal module boundary

No code is moved in 1.0 yet. This is the target for Gate 1.1+:

```text
stage_letter/
  domain/
    creators.py
    follows.py
    live.py
    notifications.py

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
      migrations/
    adapters/
      base.py
      douyin.py
      bilibili.py
      huya.py
      douyu.py
    source_composition/
    queue/
    wechat/

  workers/
    probe.py
    notify.py

  api/
  miniapp/
```

Exact package naming may change before Gate 1.0 closes; semantic ownership may not.

## 7. Reuse policy

Gate 1 must reuse accepted semantics, not rewrite them from memory.

Candidate provenance map:

```text
Gate 0B state_engine.py       -> formal live state domain/service
Gate 0B sqlite_store.py       -> persistence behavior reference, not production DB choice
Gate 0C source_composition.py -> formal source composition service
Gate 0C platform_health.py    -> source/runtime health model
Gate 0D notification_truth.py -> eligibility + logical delivery identity
Gate 0D provider_result.py    -> provider normalization
Gate 0D delivery_retry.py     -> durable delivery runtime
Gate 0E golden_path.py        -> integration contract / regression test oracle
```

The formal implementation may use PostgreSQL/SQLAlchemy/Redis/Dramatiq, but changing infrastructure must not change these semantics.

## 8. Legacy code quarantine rule

Until Gate 1.0 closes, existing formal files such as `core/models.py`, old state machines, old notification workers, and old adapter status enums are **legacy baseline**, not automatically authoritative.

Do not delete them yet. Do not extend them with new V0.1 features until the drift items above have an explicit migration decision.

This avoids accidentally building Gate 1 on semantics that Gate 0 already disproved.

## 9. Gate 1.0 acceptance criteria

Gate 1.0 PASS requires 8/8:

```text
1. Gate 0B/0C/0D/0E truths are recorded as formal invariants
2. ten-domain-entity model is frozen
3. legacy-vs-accepted drift matrix is complete
4. formal module ownership is frozen
5. PostgreSQL migration strategy is frozen
6. experiment-to-formal reuse map is frozen
7. legacy quarantine / no-copy list is frozen
8. Gate 1.1 has an executable implementation plan with test gates
```

No production logic migration begins before this acceptance matrix is complete.

## 10. Current decision

```text
Gate 0A    DEGRADED / inherited known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E    PASS
Git baseline c841a33d PASS

Gate 1.0    CURRENT
Gate 1.1    NOT STARTED
```

Gate 0A's deferred real lifecycle evidence gap remains visible. Gate 1.0 must not silently upgrade it to PASS.
