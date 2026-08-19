# Gate 1.6 — Notification Queue + WeChat Delivery

Status: **CURRENT / 1.6-1 ELIGIBILITY POLICY LANDED / LOCAL EVIDENCE PENDING**

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
Gate 1.6-1  Eligibility + Logical Delivery Contract              CURRENT
Gate 1.6-2  Recipient / Grant Resolution + Durable Enqueue        NOT STARTED
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

Permanent Gate 0D safety constraints also remain inherited:

```text
SENT is terminal for one logical delivery
SENT does not prove global grant exhaustion
IN_FLIGHT at crash/restart -> AMBIGUOUS -> no blind resend
exact same provider payload may produce duplicate external notifications
no provider-backed exactly-once claim
non-zero provider codes stay conservative unless evidence-backed
```

## 4. Gate 1.6-1 — CURRENT

### 4.1 Pure formal policy

Landed:

```text
stage_letter/domain/notification_policy.py
```

The policy introduces:

```text
EligibilityReason
NotificationTarget
EligibilityDecision
evaluate_notification_eligibility(...)
build_pending_delivery(...)
```

`NotificationTarget` is one already-resolved user/account/channel truth snapshot. Its `grant_state` is notification channel/provider truth supplied to the policy; this does not make grant truth a Creator, PlatformAccount, Follow, or NotificationPreference field, and Gate 1.6-1 deliberately does not define grant storage.

### 4.2 Eligibility ordering

The formal policy preserves the accepted Gate 0D reason ordering:

```text
wrong event type         -> WRONG_EVENT_TYPE
BOOTSTRAP_LIVE           -> BOOTSTRAP_LIVE
not following            -> NOT_FOLLOWING
preference disabled      -> NOTIFICATION_DISABLED
grant != GRANTED         -> GRANT_NOT_GRANTED
all required truths      -> ELIGIBLE
```

A target account mismatch is an invariant error rather than an ineligible decision.

### 4.3 Logical delivery construction

`build_pending_delivery()` creates no side effect. For an eligible decision it builds one formal `NotificationDelivery` value with:

```text
key.user_id       = target.user_id
key.live_event_id = event.event_id
key.channel       = decision.channel
account_id        = event.account_id
session_id        = event.session_id
created_at        = event.occurred_at
state             = PENDING
```

For an ineligible decision it returns no delivery.

This pure constructor does not claim durable idempotency by itself. Durable duplicate suppression remains the already-frozen `NotificationRepository.create_delivery()` + database uniqueness boundary over `(user_id, live_event_id, channel)` and will be exercised by Gate 1.6-2.

### 4.4 Explicit non-goals of 1.6-1

Gate 1.6-1 does not:

```text
query followers
query notification preferences
persist or infer grant state
create database rows
call WeChat
obtain access tokens
interpret provider error codes
change delivery execution state
mutate LiveSession / LiveEvent / creator live truth
```

### 4.5 Landed deterministic contracts

```text
tests/gate1/test_gate16_notification_eligibility.py  12 tests
```

The contracts cover the complete eligibility matrix, account mismatch, decision truth/reason consistency, eligible PENDING delivery construction, ineligible no-delivery behavior, exact logical delivery key shape, and pure-domain dependency boundaries.

Accepted entering baseline is 345 tests. Twelve new tests raise the expected complete Gate 1 suite to:

```text
357 / 357
```

### 4.6 Acceptance — Gate 1.6-1

```text
A. Gate 1.5 PASS / CLOSED                         PASS
B. LIVE_STARTED + TRANSITION required            PASS / CONTRACT
C. Follow + enabled preference required           PASS / CONTRACT
D. only GRANTED grant truth eligible              PASS / CONTRACT
E. BOOTSTRAP_LIVE never live-start-notifies       PASS / CONTRACT
F. logical key = user + live_event + channel      PASS / CONTRACT
G. no provider/persistence/live-truth side effect PASS / CONTRACT
H. dedicated Gate 1.6-1 contracts                PENDING / 12
I. complete Gate 1 suite                          PENDING / expected 357
```

Gate 1.6-1 remains CURRENT until H-I pass.

## 5. Next slice

Gate 1.6-2 will resolve actual recipients from formal Follow + NotificationPreference persistence, define the channel/grant-resolution port without pretending grant state belongs to the live domain, and atomically create at most one durable `NotificationDelivery` per `(user_id, live_event_id, channel)`.

It must distinguish:

```text
no Follow             -> no delivery
preference absent/disabled -> no delivery unless an explicit existing contract proves otherwise
non-GRANTED grant     -> no live-start delivery
eligible duplicate    -> reuse existing logical delivery
eligible new target   -> one PENDING durable delivery
```

Any default for a missing `NotificationPreference` must be proven from the accepted formal product/schema contract before implementation; Gate 1.6-2 must not silently invent that default.

## 6. Stop rules

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

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE real-provider lifecycle evidence gap. Gate 1.6 proceeds from already-persisted canonical `LiveEvent` facts and does not use notification success to repair or reinterpret that missing provider lifecycle evidence.
