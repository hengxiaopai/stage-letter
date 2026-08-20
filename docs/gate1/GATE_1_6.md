# Gate 1.6 — Notification Queue + WeChat Delivery

Status: **CURRENT / 1.6-2 CODE LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.5 PASS / CLOSED.

## 1. Goal

Gate 1.6 consumes already-persisted canonical `LiveEvent` facts and owns notification eligibility, logical delivery creation/queueing, crash-safe delivery execution, conservative provider-result normalization, and WeChat subscribe-message delivery.

```text
canonical LiveEvent
  -> eligibility policy
  -> recipient / grant resolution
  -> logical NotificationDelivery
  -> durable execution state machine
  -> WeChat provider adapter
  -> provider result normalization
```

Notification failure must never mutate creator live truth, `LiveSession`, or `LiveEvent`.

## 2. Internal slices

```text
Gate 1.6-1  Eligibility + Logical Delivery Contract              PASS / CLOSED
Gate 1.6-2  Recipient / Grant Resolution + Durable Enqueue        CURRENT / CODE LANDED
Gate 1.6-3  Delivery State Machine + Crash / Retry Recovery       NOT STARTED
Gate 1.6-4  WeChat Provider Adapter + Result Normalization         NOT STARTED
Gate 1.6-5  Restart + Real WeChat Acceptance                       NOT STARTED
```

## 3. Inherited Gate 0D truth

Gate 0D remains the accepted oracle for notification semantics, but formal runtime never imports `experiments/*`.

Eligibility requires all of:

```text
LiveEvent.event_type == LIVE_STARTED
LiveEvent.cause      == TRANSITION
Follow               == true
NotificationPreference.enabled == true
WeChat grant state   == GRANTED
```

Therefore these do not create a live-start delivery:

```text
LIVE_ENDED
BOOTSTRAP_LIVE
not following
notification disabled
DENIED / UNKNOWN / EXHAUSTED grant truth
```

Logical delivery identity remains exactly:

```text
(user_id, live_event_id, channel)
```

The channel for this gate begins with `WECHAT_SUBSCRIBE`.

Permanent Gate 0D safety constraints remain inherited:

```text
SENT is terminal for one logical delivery
SENT does not prove global grant exhaustion
IN_FLIGHT at crash/restart -> AMBIGUOUS -> no blind resend
exact same provider payload may produce duplicate external notifications
no provider-backed exactly-once claim
non-zero provider codes stay conservative unless evidence-backed
```

## 4. Gate 1.6-1 — PASS / CLOSED

Gate 1.6-1 landed the pure formal eligibility policy in:

```text
stage_letter/domain/notification_policy.py
```

It introduced `NotificationTarget`, `EligibilityDecision`, the accepted eligibility matrix, and pure `PENDING` logical-delivery construction. It performs no recipient lookup, persistence, grant lookup, provider call, access-token work, or live-truth mutation.

Accepted evidence:

```text
Gate 1.6-1 dedicated contracts   12 / 12 PASS
complete Gate 1 suite            357 / 357 PASS
```

Therefore Gate 1.6-1 is closed.

## 5. Gate 1.6-2 — CURRENT / CODE LANDED

### 5.1 Recipient resolution

`FollowRepository` now supports stable account fan-out in ascending user-id order with an optional event-time cutoff:

```text
Follow.platform_account_id == LiveEvent.account_id
Follow.created_at <= LiveEvent.occurred_at
```

This prevents a user who follows after a `LIVE_STARTED` event from receiving a historical "just went live" notification when a delayed planner processes that event later.

The forward migration adds the fan-out index:

```text
idx_g16_follows_account_user
  (platform_account_id, user_id)
```

### 5.2 Follow / NotificationPreference contract repair

The accepted subscription contract creates notifications enabled by default. Formal `FollowApplicationService.follow_account()` now closes the previous split-model gap:

```text
new Follow + missing preference -> create NotificationPreference(enabled=True)
existing preference             -> preserve existing value
existing enabled=False          -> never silently overwrite to True
```

The migration deterministically repairs pre-existing formal Follow rows that lack a NotificationPreference. It does not invent grant/provider truth.

The fan-out read path remains conservative: if a preference is still missing, the notification planner skips that recipient rather than silently treating missing data as enabled.

### 5.3 Grant-resolution boundary

The existing `wechat_subscription_grants` table remains the optimistic local WeChat grant ledger. Gate 1.6-2 does **not** create a second grant table and does not promote provider grant truth into canonical live metadata.

The formal application boundary receives an immutable `WeChatGrantLedger` through `GrantRepository`. The SQLAlchemy implementation uses a separate Core `MetaData` mapping, so Gate 1's frozen ten-table canonical `Base.metadata` remains unchanged.

Resolution is deliberately conservative:

```text
available = max(0, granted_count - consumed_count)

available > 0             -> GRANTED
missing row               -> EXHAUSTED
available == 0            -> EXHAUSTED
consumed > granted        -> EXHAUSTED
```

The optimistic ledger never infers `DENIED` or `UNKNOWN`; WeChat send results remain the later provider authority.

### 5.4 Durable enqueue orchestration

Landed:

```text
stage_letter/application/services/notification_enqueue.py
```

`NotificationEnqueueApplicationService` consumes one already-persisted canonical event and performs:

```text
load canonical LiveEvent
  -> list event-time-eligible followers
  -> resolve NotificationPreference
  -> resolve optimistic WeChat grant ledger
  -> reuse Gate 1.6-1 eligibility policy
  -> build PENDING NotificationDelivery
  -> NotificationRepository.create_delivery()
```

Durable identity remains the existing database uniqueness boundary:

```text
(user_id, live_event_id, channel)
```

Therefore:

```text
first eligible enqueue     -> CREATED
same logical enqueue retry -> REUSED_EXISTING
```

This is canonical logical-delivery idempotency only. It does not claim notification worker, provider, or external WeChat exactly-once execution.

### 5.5 Slice boundary preserved

Gate 1.6-2 deliberately does **not** wire notification enqueue into the worker composition root. Gate 1.4's worker-composition freeze remains intact, and delivery scheduling / state-machine ownership is reserved for Gate 1.6-3.

Gate 1.6-2 also does not:

```text
call WeChat
obtain access_token
consume grant balance after provider send
interpret provider result codes
transition PENDING -> IN_FLIGHT / retry / terminal states
blind-retry AMBIGUOUS deliveries
mutate LiveSession / LiveEvent / creator truth
import experiments or legacy notify workers
```

### 5.6 Migration

New forward-only revision:

```text
f16e2a7c4d10
  down_revision = d14e7c9a5b30
```

It only:

```text
adds idx_g16_follows_account_user
repairs missing NotificationPreference rows from existing Follow truth
```

It does not create or rewrite `wechat_subscription_grants` and does not fabricate provider evidence.

### 5.7 Deterministic contracts

Dedicated Gate 1.6-2 contracts:

```text
tests/gate1/test_gate16_notification_enqueue.py  15 tests
```

They cover:

```text
positive / missing / exhausted / over-consumed grant resolution
existing disabled preference preservation
missing canonical event failure
recipient event-time cutoff
missing preference conservative skip
disabled preference skip
missing/exhausted grant skip
eligible PENDING creation
duplicate logical delivery reuse
stable pagination cursor
provider/network/live-mutation boundary
migration lineage / non-destructive repair
frozen ten-table metadata preservation
```

Accepted complete Gate 1 baseline was 357. Fifteen new tests raise the expected complete suite to:

```text
372 / 372
```

### 5.8 Real PostgreSQL acceptance

Landed:

```text
scripts/gate16_notification_enqueue_probe.py
```

The probe requires migration head `f16e2a7c4d10` and verifies:

```text
fan-out index exists
late follower is excluded by event-time cutoff
missing preference is skipped
notification-disabled target is skipped
exhausted grant target is skipped
eligible target creates one PENDING delivery
second enqueue reuses existing logical delivery
final delivery row count remains one
no WeChat/provider call occurs
no provider/notification exactly-once claim is made
```

Expected core evidence:

```text
status                         PASS
migration_head                 f16e2a7c4d10
fanout_index_present           true

first_enqueue.created          1
first_enqueue.reused_existing  0

second_enqueue.created         0
second_enqueue.reused_existing 1

final_delivery_count           1
wechat_provider_called         false
provider_exactly_once_claimed  false
notification_exactly_once_claimed false
```

### 5.9 Acceptance — Gate 1.6-2

```text
A. Gate 1.6-1 PASS / CLOSED                        PASS
B. event-time recipient cutoff                     CODE / CONTRACT
C. new Follow gets missing default preference      CODE / CONTRACT
D. existing disabled preference preserved          CODE / CONTRACT
E. grant ledger remains separate from live domain  CODE / CONTRACT
F. missing / exhausted grant not eligible          CODE / CONTRACT
G. durable user+event+channel identity reused       CODE / CONTRACT
H. no WeChat/provider/live-truth side effect        CODE / CONTRACT
I. migration head f16e2a7c4d10                     CODE / PENDING LOCAL
J. dedicated Gate 1.6-2 contracts                  PENDING / expected 15
K. complete Gate 1 suite                            PENDING / expected 372
L. real PostgreSQL durable-enqueue probe            PENDING
```

Gate 1.6-2 remains CURRENT until I-L pass.

## 6. Next slice

Gate 1.6-3 will own the durable delivery execution state machine and crash/retry recovery. It must preserve the inherited Gate 0D rule that an `IN_FLIGHT` delivery observed after crash/restart becomes `AMBIGUOUS` and is not blindly resent.

Gate 1.6-3 must not start until Gate 1.6-2 is PASS / CLOSED.

## 7. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
BOOTSTRAP_LIVE generating a live-start notification
LIVE_ENDED generating a live-start notification
UNKNOWN/DENIED/EXHAUSTED grant treated as GRANTED
successful send inferred as global grant exhaustion
notification/provider failure mutating live truth
payload equality treated as provider deduplication
blind resend of AMBIGUOUS delivery
exactly-once external delivery claim
raw non-zero provider code promoted without evidence
secret material persisted or logged
formal runtime importing experiments or legacy workers/notify
```

## 8. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.6 proceeds from already-persisted canonical `LiveEvent` facts and does not use notification success to repair or reinterpret that missing provider lifecycle evidence.
