# Gate 1.6 — Notification Queue + WeChat Delivery

Status: **CURRENT / 1.6-4 CODE LANDED / LOCAL EVIDENCE PENDING**

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
  -> real-account acceptance
```

Notification/provider failure must never mutate creator live truth, `LiveSession`, or `LiveEvent`.

## 2. Internal slices

```text
Gate 1.6-1  Eligibility + Logical Delivery Contract               PASS / CLOSED
Gate 1.6-2  Recipient / Grant Resolution + Durable Enqueue        PASS / CLOSED
Gate 1.6-3  Delivery State Machine + Crash / Retry Recovery        PASS / CLOSED
Gate 1.6-4  WeChat Provider Adapter + Result Normalization         CURRENT / CODE LANDED
Gate 1.6-5  Restart + Real WeChat Acceptance                       NOT STARTED
```

## 3. Permanent safety constraints

```text
LIVE_STARTED + TRANSITION is required for live-start delivery
BOOTSTRAP_LIVE never creates a live-start notification
logical delivery identity = (user_id, live_event_id, channel)
SENT is terminal for one logical delivery
SENT does not prove global grant exhaustion
stale IN_FLIGHT -> AMBIGUOUS -> no blind resend
message payload equality does not imply provider deduplication
unknown provider result is never promoted to success/retry without evidence
no worker/provider/external exactly-once claim
secret/token material is never persisted or exposed through normalized outcomes
```

Gate 0A remains **DEGRADED** for the deferred same-creator real-provider OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Notification evidence does not replace that missing provider evidence.

## 4. Gate 1.6-1 — PASS / CLOSED

Landed pure eligibility and logical PENDING-delivery construction.

Accepted evidence:

```text
Gate 1.6-1 dedicated contracts   12 / 12 PASS
complete Gate 1 suite            357 / 357 PASS
```

## 5. Gate 1.6-2 — PASS / CLOSED

Landed:

```text
event-time follower fan-out
NotificationPreference default/repair contract
formal optimistic WeChat grant-ledger read boundary
durable PENDING NotificationDelivery enqueue
PostgreSQL idempotent reuse by (user,event,channel)
```

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

## 6. Gate 1.6-3 — PASS / CLOSED

Gate 1.6-3 froze the durable delivery execution state machine.

Automatic claim is limited to:

```text
PENDING
WAITING_RETRY where next_attempt_at <= now
```

Claim:

```text
PENDING / due WAITING_RETRY
  -> IN_FLIGHT
  -> attempt += 1
  -> in_flight_at = now
```

One persisted IN_FLIGHT attempt may resolve to:

```text
WAITING_RETRY
WAITING_AUTH
BLOCKED_CONFIG
SENT
FAILED_TERMINAL
AMBIGUOUS
```

Crash safety remains deliberately conservative:

```text
stale IN_FLIGHT
  -> AMBIGUOUS
  -> preserve prior in_flight_at for forensic evidence
  -> error_code = CRASH_RECOVERY_AMBIGUOUS
  -> never blind reclaim
```

PostgreSQL claim coordination uses row locking with `FOR UPDATE SKIP LOCKED`. This coordinates durable claims but does not establish worker/provider exactly-once execution.

Execution indexes remain:

```text
idx_g163_delivery_due
  (state, next_attempt_at, id)

idx_g163_delivery_inflight
  (state, in_flight_at, id)
```

Accepted local evidence:

```text
Gate 1.6-3 dedicated contracts      18 / 18 PASS
complete Gate 1 suite               390 / 390 PASS
migration head                      a63f4b2d9e71
PostgreSQL state-machine probe      PASS
execution_indexes_present           true
concurrent_claim_non_null_count     1
restart_recovery.recovered_ambiguous 1
first_delivery_after_recovery.state AMBIGUOUS
claim_after_ambiguous               false
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

Therefore Gate 1.6-3 is closed.

## 7. Gate 1.6-4 — CURRENT / CODE LANDED

### 7.1 Application-owned provider contract

Landed:

```text
stage_letter/application/notification_providers.py
```

The formal application boundary now owns semantic WeChat live-start messages and a finite normalized provider vocabulary:

```text
ProviderOutcomeKind
  ACCEPTED
  AUTH_REQUIRED
  CONFIG_BLOCKED
  RETRYABLE
  TERMINAL_FAILURE
  AMBIGUOUS

GrantEffect
  CONSUME
  PRESERVE
```

`WeChatLiveStartMessage` contains semantic content only. It does not carry a provider dedupe key and does not imply external exactly-once behavior.

### 7.2 Formal WeChat HTTP adapter

Landed:

```text
stage_letter/infrastructure/notifications/wechat.py
```

It contains:

```text
WeChatSubscribeFormalAdapter
HttpxWeChatProviderGateway
build_live_start_template_data(...)
normalize_wechat_response(...)
```

Provider-specific five-field template translation remains in infrastructure:

```text
thing1  anchor name
thing2  room title
time3   start time
thing5  theme
thing6  activity
```

The HTTP gateway owns only private in-memory access-token caching and transport. It imports no `core`, `api`, legacy `workers/notify`, `platform_adapters`, or `experiments` code.

### 7.3 Evidence-backed result normalization

Only accepted project evidence receives specific semantics:

```text
errcode 0
  -> ACCEPTED
  -> GrantEffect.CONSUME

errcode 43101
  -> AUTH_REQUIRED
  -> GrantEffect.CONSUME

errcode 40037
  -> CONFIG_BLOCKED
  -> GrantEffect.PRESERVE

errcode 45009
  -> RETRYABLE
  -> GrantEffect.PRESERVE

errcode 40001 / 42001
  -> RETRYABLE
  -> invalidate cached access token
  -> GrantEffect.PRESERVE
```

Conservative unknown handling:

```text
explicit HTTP 5xx
  -> RETRYABLE

access-token acquisition failure before message POST
  -> RETRYABLE

message POST transport failure / response loss
  -> AMBIGUOUS
  -> never blind retry

malformed provider response
  -> AMBIGUOUS

arbitrary unknown non-zero errcode
  -> AMBIGUOUS
  -> never silently promoted to retry/success
```

Transport exception text is not exposed through normalized outcomes. Fixed safe messages are used so a lower-level exception cannot leak token/secret material.

### 7.4 Mapping normalized outcomes onto Gate 1.6-3

Landed:

```text
stage_letter/application/services/wechat_delivery.py
```

One already-persisted IN_FLIGHT attempt maps as follows:

```text
ACCEPTED        -> SENT
AUTH_REQUIRED   -> WAITING_AUTH
CONFIG_BLOCKED  -> BLOCKED_CONFIG
RETRYABLE       -> WAITING_RETRY
TERMINAL_FAILURE-> FAILED_TERMINAL
AMBIGUOUS       -> AMBIGUOUS
```

Retry policy is explicit and bounded:

```text
base delay      10s
exponential     10,20,40,...
max delay       300s
max attempts    8
```

A retryable outcome at the configured attempt ceiling becomes `FAILED_TERMINAL` rather than looping forever.

### 7.5 Grant-effect boundary

Gate 1.6-4 normalizes whether provider evidence says the optimistic ledger should later be consumed or preserved, but it deliberately does **not** mutate `wechat_subscription_grants` yet.

```text
0 / 43101 -> CONSUME
40037 / 45009 / token errors / unknowns -> PRESERVE
```

Real durable grant consumption, user/openid resolution, runtime worker wiring, and real WeChat acceptance are reserved for Gate 1.6-5 so provider I/O and durable accounting can be accepted together.

### 7.6 No migration

Gate 1.6-4 adds no table, column, constraint, or index.

Expected migration head remains:

```text
a63f4b2d9e71
```

### 7.7 Dedicated contracts

Landed:

```text
tests/gate1/test_gate16_wechat_provider.py
  20 tests

tests/gate1/test_gate16_wechat_provider_state_integration.py
  2 tests
```

Dedicated Gate 1.6-4 total:

```text
22 tests
```

They cover:

```text
semantic message validation
five-field payload shape / truncation
0 / 43101 / 40037 / 45009 / 40001 / 42001 normalization
HTTP 5xx handling
unknown/malformed result ambiguity
pre-send token failure vs post-send transport ambiguity
private token cache invalidation
secret-free send payload / normalized outcome
ACCEPTED -> SENT
AUTH_REQUIRED -> WAITING_AUTH
CONFIG_BLOCKED -> BLOCKED_CONFIG
RETRYABLE -> WAITING_RETRY
retry exhaustion -> FAILED_TERMINAL
AMBIGUOUS -> AMBIGUOUS / no blind retry
actual NotificationDeliveryApplicationService ambiguous persistence
application/infrastructure dependency boundaries
```

Accepted entering complete Gate 1 baseline is 390. Twenty-two new tests raise the expected complete suite to:

```text
412 / 412
```

### 7.8 Deterministic normalization probe

Landed:

```text
scripts/gate16_wechat_provider_normalization_probe.py
```

This probe intentionally uses no real WeChat account, no access token, no app secret, and no provider network call. It verifies the normalized outcome matrix and the state mapping before the real-account acceptance slice.

Expected core evidence:

```text
status                          PASS
migration_head_expected         a63f4b2d9e71
normalization.0.kind            ACCEPTED
normalization.43101.kind        AUTH_REQUIRED
normalization.40037.kind        CONFIG_BLOCKED
normalization.45009.kind        RETRYABLE
normalization.40001.kind        RETRYABLE
normalization.42001.kind        RETRYABLE
normalization.unknown.kind      AMBIGUOUS
normalization.token_unavailable.kind RETRYABLE
normalization.send_transport.kind    AMBIGUOUS
state_mapping.accepted.state    SENT
state_mapping.auth_required.state WAITING_AUTH
state_mapping.config_blocked.state BLOCKED_CONFIG
state_mapping.retryable.state   WAITING_RETRY
state_mapping.ambiguous.state   AMBIGUOUS
real_wechat_called              false
access_token_loaded             false
app_secret_loaded               false
provider_exactly_once_claimed   false
notification_exactly_once_claimed false
production_approved             false
```

### 7.9 Acceptance — Gate 1.6-4

```text
A. Gate 1.6-3 PASS / CLOSED                         PASS
B. formal WeChat provider contract                 CODE / CONTRACT
C. five-field provider payload translation         CODE / CONTRACT
D. evidence-backed known-code normalization        CODE / CONTRACT
E. unknown/transport ambiguity remains conservative CODE / CONTRACT
F. normalized outcomes map to frozen 1.6-3 states CODE / CONTRACT
G. no real WeChat/secret/grant mutation yet        CODE / CONTRACT
H. migration head remains a63f4b2d9e71             PENDING LOCAL
I. dedicated Gate 1.6-4 contracts                  PENDING / expected 22
J. complete Gate 1 suite                            PENDING / expected 412
K. deterministic provider-normalization probe      PENDING
```

Gate 1.6-4 remains CURRENT until H-K pass.

## 8. Next slice

Gate 1.6-5 will perform final runtime wiring and restart + real WeChat acceptance. It must cover, at minimum:

```text
resolve recipient openid and provider message input
re-check / account for optimistic grant before real send
claim IN_FLIGHT before provider I/O
apply normalized provider outcome
atomically record evidence-backed grant consumption where required
prove retry/restart behavior around real provider attempts
prove stale IN_FLIGHT -> AMBIGUOUS remains no-blind-resend
prove no secret/token persistence or logging
exercise a real accepted WeChat send with controlled test account when available
retain honest no-exactly-once claims
```

Gate 1.6-5 must not use notification success to repair Gate 0A provider lifecycle evidence.

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
