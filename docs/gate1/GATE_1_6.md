# Gate 1.6 — Notification Queue + WeChat Delivery

Status: **CURRENT / 1.6-3 CODE LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.5 PASS / CLOSED.

## 1. Goal

Gate 1.6 consumes already-persisted canonical `LiveEvent` facts and owns notification eligibility, recipient/grant resolution, logical delivery creation, durable execution state, conservative provider-result normalization, and WeChat subscribe-message delivery.

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
Gate 1.6-1  Eligibility + Logical Delivery Contract               PASS / CLOSED
Gate 1.6-2  Recipient / Grant Resolution + Durable Enqueue        PASS / CLOSED
Gate 1.6-3  Delivery State Machine + Crash / Retry Recovery        CURRENT / CODE LANDED
Gate 1.6-4  WeChat Provider Adapter + Result Normalization         NOT STARTED
Gate 1.6-5  Restart + Real WeChat Acceptance                       NOT STARTED
```

## 3. Inherited Gate 0D truth

Eligibility requires all of:

```text
LiveEvent.event_type == LIVE_STARTED
LiveEvent.cause      == TRANSITION
Follow               == true
NotificationPreference.enabled == true
WeChat grant state   == GRANTED
```

Logical delivery identity remains exactly:

```text
(user_id, live_event_id, channel)
```

Permanent safety constraints remain inherited:

```text
SENT is terminal for one logical delivery
SENT does not prove global grant exhaustion
IN_FLIGHT at crash/restart -> AMBIGUOUS -> no blind resend
exact same provider payload may produce duplicate external notifications
no provider-backed exactly-once claim
non-zero provider codes stay conservative unless evidence-backed
```

## 4. Gate 1.6-1 — PASS / CLOSED

Landed the pure formal notification eligibility policy and logical `PENDING` delivery construction.

Accepted evidence:

```text
Gate 1.6-1 dedicated contracts   12 / 12 PASS
complete Gate 1 suite            357 / 357 PASS
```

## 5. Gate 1.6-2 — PASS / CLOSED

Gate 1.6-2 added:

```text
event-time follower fan-out
NotificationPreference default/repair contract
formal optimistic WeChat grant ledger boundary
durable NotificationDelivery enqueue
PostgreSQL idempotent reuse by (user,event,channel)
```

Accepted local evidence:

```text
complete Gate 1 suite            372 / 372 PASS
migration head                   f16e2a7c4d10
PostgreSQL enqueue probe         PASS
fanout_index_present             true
first enqueue created            1
second enqueue reused_existing   1
final delivery count             1
wechat_provider_called           false
provider_exactly_once_claimed    false
notification_exactly_once_claimed false
```

The accepted probe examined four candidate recipients and proved the conservative split:

```text
eligible target             -> one PENDING delivery
missing preference          -> skipped
other ineligible targets    -> skipped
same logical enqueue retry  -> existing delivery reused
```

`production_approved=false` remains correct because no real WeChat send occurred in 1.6-2.

## 6. Gate 1.6-3 — CURRENT / CODE LANDED

### 6.1 Delivery execution metadata

The formal `NotificationDelivery` value now carries the already-existing persistence execution fields:

```text
attempt
next_attempt_at
in_flight_at
sent_at
error_code
error_message
```

Gate 1.1's frozen state-only value construction remains readable/constructible. Strict execution metadata is validated when a state transition is actually performed, rather than by breaking older value construction contracts.

### 6.2 Claimable states

Only these states may be automatically claimed:

```text
PENDING
WAITING_RETRY where next_attempt_at <= now
```

Claim transition:

```text
PENDING / due WAITING_RETRY
  -> IN_FLIGHT
  -> attempt += 1
  -> in_flight_at = now
  -> next_attempt_at = null
```

Automatic blind retry is **not** allowed for:

```text
IN_FLIGHT
WAITING_AUTH
BLOCKED_CONFIG
AMBIGUOUS
SENT
FAILED_TERMINAL
```

### 6.3 Attempt outcome state machine

One persisted `IN_FLIGHT` attempt can transition to:

```text
WAITING_RETRY
WAITING_AUTH
BLOCKED_CONFIG
SENT
FAILED_TERMINAL
AMBIGUOUS
```

Gate 1.6-3 does not decide which WeChat result maps to which state. That provider-result normalization belongs to Gate 1.6-4.

Generic durable mechanics are now frozen:

```text
IN_FLIGHT -> WAITING_RETRY
  stores explicit next_attempt_at

WAITING_RETRY -> IN_FLIGHT
  only when due
  increments attempt

IN_FLIGHT -> SENT
  records sent_at
  SENT is terminal

IN_FLIGHT -> WAITING_AUTH / BLOCKED_CONFIG / FAILED_TERMINAL
  no automatic blind claim
```

### 6.4 Crash/restart recovery

A stale persisted `IN_FLIGHT` row is never returned to `PENDING` or `WAITING_RETRY` merely because the process restarted.

```text
stale IN_FLIGHT
  -> AMBIGUOUS
  -> preserve prior in_flight_at for forensic evidence
  -> error_code = CRASH_RECOVERY_AMBIGUOUS
  -> no blind resend
```

This is deliberately conservative because after a process loss the application cannot know whether the provider request was never issued, issued but not accepted, or accepted with the response lost.

### 6.5 PostgreSQL claim coordination

`NotificationRepository` now exposes stable due/stale selection and row locking.

The concrete PostgreSQL implementation uses:

```text
SELECT ... FOR UPDATE SKIP LOCKED
```

A delivery claim is persisted and committed before any later provider I/O. Multiple workers may race to inspect the same due candidate, but only a locked current-state row can be transitioned to `IN_FLIGHT`.

This is queue coordination, not worker/provider exactly-once execution.

### 6.6 Execution indexes

New forward-only migration:

```text
a63f4b2d9e71
  down_revision = f16e2a7c4d10
```

It adds only:

```text
idx_g163_delivery_due
  (state, next_attempt_at, id)

idx_g163_delivery_inflight
  (state, in_flight_at, id)
```

No table is added, no delivery identity changes, and no delivery/grant truth is rewritten.

### 6.7 Application boundary

Landed:

```text
stage_letter/application/services/notification_delivery.py
```

It owns:

```text
claim_next_due(...)
schedule_retry(...)
mark_sent(...)
mark_waiting_auth(...)
mark_blocked_config(...)
mark_failed_terminal(...)
recover_stale_in_flight(...)
```

It performs no provider/network request, does not obtain an access token, and does not mutate `LiveSession`, `LiveEvent`, or creator live truth.

Gate 1.4's worker-composition freeze remains intact; no notification/provider worker is wired in this slice.

### 6.8 Dedicated contracts

Landed:

```text
tests/gate1/test_gate16_delivery_state_machine.py  18 tests
```

The contracts cover:

```text
PENDING claim
explicit retry scheduling
not-due retry rejection
due retry attempt increment
SENT terminal semantics
WAITING_AUTH / BLOCKED_CONFIG non-blind-retry semantics
FAILED_TERMINAL semantics
crash -> AMBIGUOUS recovery
frozen state-only construction compatibility
application claim/save/commit behavior
SKIP LOCKED candidate handling
invalid retry transition rejection
stale recovery / no-op recovery
migration + model index parity
repository execution metadata persistence
provider/network/live-truth boundary
```

Accepted entering complete Gate 1 baseline is 372. Eighteen new contracts raise the expected suite to:

```text
390 / 390
```

### 6.9 Real PostgreSQL acceptance

Landed:

```text
scripts/gate16_delivery_state_machine_probe.py
```

The probe requires migration head `a63f4b2d9e71` and verifies two independent durable paths.

Crash/concurrency path:

```text
one PENDING delivery
  -> two concurrent claim transactions
  -> exactly one claim winner
  -> persisted IN_FLIGHT attempt=1
  -> process/runtime restart
  -> stale recovery
  -> AMBIGUOUS
  -> later automatic claim returns none
```

Retry/terminal path:

```text
second PENDING delivery
  -> claim attempt=1
  -> WAITING_RETRY with explicit due time
  -> before due: no claim
  -> at due: claim attempt=2
  -> SENT
  -> later automatic claim returns none
```

Expected core evidence:

```text
status                              PASS
migration_head                      a63f4b2d9e71
execution_indexes_present           true
concurrent_claim_non_null_count     1

first_delivery_after_claim.state    IN_FLIGHT
first_delivery_after_claim.attempt  1
restart_recovery.recovered_ambiguous 1
first_delivery_after_recovery.state AMBIGUOUS
claim_after_ambiguous               false

retry_first_attempt                 1
waiting_retry_state                 WAITING_RETRY
retry_before_due_claimed            false
retry_second_attempt                2
sent_state                          SENT
sent_terminal                       true
claim_after_sent                    false

final_ambiguous_count               1
final_sent_count                    1
wechat_provider_called              false
worker_exactly_once_claimed         false
provider_exactly_once_claimed       false
notification_exactly_once_claimed   false
production_approved                 false
```

### 6.10 Acceptance — Gate 1.6-3

```text
A. Gate 1.6-2 PASS / CLOSED                      PASS
B. execution-state transitions                  CODE / CONTRACT
C. only PENDING/due retry automatically claimable CODE / CONTRACT
D. SENT terminal                                CODE / CONTRACT
E. stale IN_FLIGHT -> AMBIGUOUS                 CODE / CONTRACT
F. AMBIGUOUS never blindly reclaimed            CODE / CONTRACT
G. transaction row-lock coordination            CODE / CONTRACT
H. no provider/network/live-truth mutation      CODE / CONTRACT
I. migration head a63f4b2d9e71                  CODE / PENDING LOCAL
J. dedicated Gate 1.6-3 contracts               PENDING / expected 18
K. complete Gate 1 suite                         PENDING / expected 390
L. real PostgreSQL crash/retry probe             PENDING
```

Gate 1.6-3 remains CURRENT until I-L pass.

## 7. Next slice

Gate 1.6-4 will add the WeChat provider adapter and evidence-backed provider-result normalization. It may map normalized outcomes into the state machine frozen by 1.6-3, but must not weaken `AMBIGUOUS` crash safety or invent external exactly-once semantics.

## 8. Stop rules

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

## 9. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.6 proceeds from already-persisted canonical `LiveEvent` facts and does not use notification success to repair or reinterpret that missing provider lifecycle evidence.
