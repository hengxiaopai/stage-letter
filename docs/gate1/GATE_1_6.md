# Gate 1.6 — Notification Queue + WeChat Delivery

Status: **CURRENT / 1.6-5 CODE LANDED / LOCAL + REAL EVIDENCE PENDING**

Entry authority: Gate 1.5 PASS / CLOSED.

## 1. Goal

Gate 1.6 consumes already-persisted canonical `LiveEvent` facts and owns:

```text
canonical LiveEvent
  -> notification eligibility
  -> recipient / preference / grant resolution
  -> durable logical NotificationDelivery
  -> crash-safe execution state machine
  -> normalized WeChat provider adapter
  -> atomic provider-outcome + grant finalization
  -> restart-safe runtime
  -> controlled real WeChat acceptance
```

Notification/provider failure must never mutate creator live truth, `LiveSession`, or `LiveEvent`.

## 2. Internal slices

```text
Gate 1.6-1  Eligibility + Logical Delivery Contract               PASS / CLOSED
Gate 1.6-2  Recipient / Grant Resolution + Durable Enqueue        PASS / CLOSED
Gate 1.6-3  Delivery State Machine + Crash / Retry Recovery        PASS / CLOSED
Gate 1.6-4  WeChat Provider Adapter + Result Normalization         PASS / CLOSED
Gate 1.6-5  Restart + Real WeChat Acceptance                       CURRENT / CODE LANDED
```

## 3. Permanent safety constraints

```text
LIVE_STARTED + TRANSITION is required for live-start delivery
BOOTSTRAP_LIVE never creates a live-start notification
logical delivery identity = (user_id, live_event_id, channel)
SENT is terminal for one logical delivery
SENT does not prove global grant exhaustion
stale IN_FLIGHT -> AMBIGUOUS -> no blind resend
payload equality does not imply provider deduplication
unknown provider result is never promoted to success/retry without evidence
provider send result is stronger than optimistic local grant balance
no worker/provider/external exactly-once claim
secret/token material is never persisted or exposed through normalized outcomes
```

Gate 0A remains **DEGRADED** for the deferred same-creator real-provider OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Notification evidence does not replace that missing provider evidence.

## 4. Gate 1.6-1 — PASS / CLOSED

Accepted evidence:

```text
Gate 1.6-1 dedicated contracts   12 / 12 PASS
complete Gate 1 suite            357 / 357 PASS
```

Landed pure eligibility and logical PENDING-delivery construction.

## 5. Gate 1.6-2 — PASS / CLOSED

Accepted evidence:

```text
complete Gate 1 suite               372 / 372 PASS
migration head                      f16e2a7c4d10
PostgreSQL enqueue probe            PASS
fanout_index_present                true
first enqueue created               1
second enqueue reused_existing      1
final delivery count                1
wechat_provider_called              false
provider_exactly_once_claimed       false
notification_exactly_once_claimed   false
```

Landed event-time recipient fan-out, preference repair/default contract, optimistic grant read boundary, and durable idempotent enqueue.

## 6. Gate 1.6-3 — PASS / CLOSED

Accepted evidence:

```text
Gate 1.6-3 dedicated contracts       18 / 18 PASS
complete Gate 1 suite                390 / 390 PASS
migration head                       a63f4b2d9e71
PostgreSQL state-machine probe       PASS
execution_indexes_present            true
concurrent_claim_non_null_count      1
restart_recovery.recovered_ambiguous 1
first_delivery_after_recovery.state  AMBIGUOUS
claim_after_ambiguous                false
retry_before_due_claimed             false
retry_second_attempt                 2
sent_state                           SENT
sent_terminal                        true
claim_after_sent                     false
```

Only PENDING / due WAITING_RETRY are automatically claimable. Stale IN_FLIGHT becomes AMBIGUOUS and is never blindly resent.

## 7. Gate 1.6-4 — PASS / CLOSED

Gate 1.6-4 added the application-owned WeChat provider contract, async HTTP gateway, five-field subscribe-message translation, bounded retry policy, and conservative provider-result normalization.

Accepted local evidence:

```text
Gate 1.6-4 contracts                 included in 412 / 412 PASS
complete Gate 1 suite                412 / 412 PASS
migration head                       a63f4b2d9e71
provider-normalization probe         PASS
```

Accepted normalization:

```text
0       -> ACCEPTED       / CONSUME  -> SENT
43101   -> AUTH_REQUIRED  / CONSUME  -> WAITING_AUTH
40037   -> CONFIG_BLOCKED / PRESERVE -> BLOCKED_CONFIG
45009   -> RETRYABLE      / PRESERVE -> WAITING_RETRY
40001   -> RETRYABLE      / PRESERVE -> WAITING_RETRY
42001   -> RETRYABLE      / PRESERVE -> WAITING_RETRY
HTTP 5xx -> RETRYABLE     / PRESERVE
pre-send token failure -> RETRYABLE  / PRESERVE
post-send response loss -> AMBIGUOUS / PRESERVE
unknown non-zero code -> AMBIGUOUS   / PRESERVE
```

The accepted probe also proved:

```text
real_wechat_called                false
access_token_loaded               false
app_secret_loaded                 false
provider_exactly_once_claimed     false
notification_exactly_once_claimed false
production_approved               false
```

Therefore Gate 1.6-4 is closed. Real grant mutation and real provider acceptance remain exclusively in Gate 1.6-5.

## 8. Gate 1.6-5 — CURRENT / CODE LANDED

### 8.1 Atomic provider-outcome finalization

Landed:

```text
stage_letter/application/services/wechat_finalize.py
```

The provider call still happens only after a durable committed IN_FLIGHT claim.

After the external result returns, Gate 1.6-5 performs one second transaction:

```text
lock current logical delivery
  -> verify exact current IN_FLIGHT attempt
  -> apply normalized outcome to frozen 1.6-3 state machine
  -> if GrantEffect.CONSUME:
       lock wechat_subscription_grants row
       consumed_count += 1
       record last_send_at / last_send_error
  -> save delivery
  -> one UoW commit
```

This closes the previous crash window where delivery state and grant accounting could otherwise commit separately.

If the real provider send happens but this finalization transaction fails:

```text
persisted delivery remains IN_FLIGHT
  -> restart recovery
  -> AMBIGUOUS
  -> no blind resend
```

The application never fabricates SENT when durable grant finalization cannot be committed.

### 8.2 Provider-authoritative grant consumption

`GrantRepository` now exposes `consume_wechat_grant(...)`.

The PostgreSQL implementation:

```text
locks (user_id, template_id) grant row
increments consumed_count exactly once per successful delivery finalization transaction
records last_send_at
records provider error code for consumed failure such as 43101
```

No availability predicate is applied at finalization time. This is intentional: the local ledger is optimistic and Gate 0A established that provider send results are stronger evidence. Therefore `consumed_count` may exceed `granted_count` when the local ledger had drifted.

A missing ledger during a provider-authoritative CONSUME outcome is an invariant failure; the transaction does not commit a fake SENT state.

### 8.3 Duplicate finalization safety

The current delivery row must still match the exact claimed attempt:

```text
state        == IN_FLIGHT
attempt      == claimed.attempt
in_flight_at == claimed.in_flight_at
key          == claimed.key
```

After the first finalization commits, a duplicate attempt sees a non-IN_FLIGHT row and is rejected before a second grant consumption.

This is durable idempotent finalization of one logical attempt. It is not an external provider exactly-once guarantee.

### 8.4 Separate notification runtime composition

Landed:

```text
workers/notification_runtime.py
workers/notification_composition.py
```

Gate 1.4's existing `workers/composition.py` remains unchanged.

The new runtime owns only notification execution:

```text
startup/restart stale recovery
  -> claim at most one due delivery
  -> resolve user openid
  -> rebuild message context from canonical event/account/profile
  -> provider send
  -> atomic provider-outcome + grant finalization
```

Known pre-send local failures remain conservative:

```text
missing openid       -> WAITING_AUTH / no provider call
invalid delivery context -> FAILED_TERMINAL / no provider call
```

Runtime construction itself opens no DB session and performs no provider request.

### 8.5 PostgreSQL atomic-finalize + restart probe

Landed:

```text
scripts/gate16_atomic_finalize_restart_probe.py
```

It uses no real WeChat network call and verifies:

```text
PENDING -> IN_FLIGHT -> ACCEPTED -> SENT
provider-authoritative grant consumption 0 -> 1
same claimed attempt finalized again -> rejected
grant remains consumed exactly once
engine dispose/restart preserves SENT + consumed_count
second delivery claimed then process restarts before provider result
stale IN_FLIGHT -> AMBIGUOUS
crash path does not consume grant
AMBIGUOUS is not automatically reclaimed
```

Expected core evidence:

```text
status                               PASS
migration_head                       a63f4b2d9e71
accepted_delivery_state              SENT
grant_consumed_after_success         1
duplicate_finalize_rejected          true
grant_consumed_after_duplicate       1
restart_sent_state                   SENT
restart_grant_consumed               1
restart_recovery.recovered_ambiguous 1
restart_recovery.delivery_state      AMBIGUOUS
grant_consumed_after_crash_recovery  1
claim_after_ambiguous                false
real_wechat_called                   false
provider_exactly_once_claimed        false
notification_exactly_once_claimed    false
production_approved                  false
```

### 8.6 Guarded real WeChat acceptance

Landed:

```text
scripts/gate16_real_wechat_acceptance.py
```

The probe has an explicit safety gate:

```text
without --send
  -> read-only preflight
  -> status ARMED
  -> no DB write
  -> no provider call
  -> prints selected user_id + canonical event_id + available grant

with --send
  -> create only the selected user's logical delivery when absent
  -> persist IN_FLIGHT claim
  -> send exactly one provider attempt
  -> atomically finalize delivery + grant effect
  -> dispose/rebuild DB runtime
  -> re-read delivery + grant
```

It never creates or updates `live_observations`, `live_sessions`, or `live_events`.

A PASS requires all of:

```text
provider outcome = ACCEPTED
provider code = 0
delivery after send = SENT
restart delivery state = SENT
grant consumed delta = +1
real_wechat_called = true
access_token_exposed = false
app_secret_exposed = false
provider_exactly_once_claimed = false
notification_exactly_once_claimed = false
production_approved = true
```

`43101`, config errors, retryable errors, and ambiguous transport results remain honest BLOCKED/non-production outcomes even though their evidence-backed state/grant effects are persisted.

### 8.7 No migration

Gate 1.6-5 adds no schema object. Expected head remains:

```text
a63f4b2d9e71
```

### 8.8 Dedicated contracts

Landed:

```text
tests/gate1/test_gate16_real_wechat_acceptance.py   16 tests
tests/gate1/test_gate16_notification_runtime.py       6 tests
```

Dedicated Gate 1.6-5 total:

```text
22 tests
```

Accepted entering full Gate 1 baseline is 412, therefore expected full suite becomes:

```text
434 / 434
```

### 8.9 Acceptance — Gate 1.6-5

```text
A. Gate 1.6-4 PASS / CLOSED                       PASS
B. delivery + grant finalization one transaction CODE / CONTRACT
C. duplicate finalization cannot double-consume  CODE / CONTRACT
D. post-send DB failure remains crash-ambiguous  CODE / CONTRACT
E. restart runtime preserves no-blind-resend      CODE / CONTRACT
F. notification runtime separately wired         CODE / CONTRACT
G. old live worker composition freeze preserved  CODE / CONTRACT
H. no new migration; head a63f4b2d9e71           PENDING LOCAL
I. dedicated Gate 1.6-5 contracts                PENDING / expected 22
J. complete Gate 1 suite                          PENDING / expected 434
K. PostgreSQL atomic-finalize/restart probe       PENDING
L. guarded real WeChat preflight                  PENDING / expected ARMED
M. one real accepted WeChat send + restart proof PENDING
```

Gate 1.6-5 and Gate 1.6 remain CURRENT until H-M pass.

## 9. Stop rules

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
unknown raw non-zero provider code promoted without evidence
secret material persisted/logged/exposed in normalized outcomes
formal runtime importing experiments or legacy workers/notify
```
