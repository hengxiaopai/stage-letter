# Gate 0D — WeChat Notification Truth

Status: **IN PROGRESS**

## Purpose

Gate 0D proves that only notification-eligible live events may enter the WeChat subscription-message delivery pipeline, and that notification/provider failures never mutate creator live truth.

Frozen boundary:

```text
LiveEvent
    -> notification eligibility
    -> delivery identity
    -> provider/grant truth
    -> send outcome

notification failure != creator OFFLINE
notification failure != LiveSession mutation
```

## Gate plan

```text
0D-1 Eligibility + logical delivery idempotency   PASS
0D-2 Provider/grant result normalization          CURRENT
0D-3 Retry / terminal-failure semantics           NOT STARTED
0D-4 Real WeChat acceptance evidence              NOT STARTED
```

---

## Gate 0D-1 — Eligibility + logical delivery idempotency — PASS

Canonical implementation:

```text
experiments/gate0d/notification_truth.py
experiments/gate0d/test_notification_truth.py
```

Eligibility requires all of:

```text
event.type  == LIVE_STARTED
event.cause == TRANSITION
Follow       == true
NotificationPreference.enabled == true
WeChat grant state == GRANTED
```

Therefore BOOTSTRAP_LIVE, LIVE_ENDED, not-following, disabled preference and non-GRANTED grant states create no live-start delivery.

Logical delivery uniqueness is:

```text
(user_id, live_event_id, channel)
```

An eligible logical delivery enters as `PENDING`; duplicate evaluation returns the existing delivery.

Clean local acceptance evidence on 2026-08-18:

```text
Ran 16 tests in 0.003s
OK
```

Acceptance: **PASS 16/16**.

The suite proves eligibility truth, BOOTSTRAP suppression, per-user/per-event separation, restart idempotency, account identity validation and that the notification layer exposes no creator live-state mutation API.

---

## Gate 0D-2 — Provider / grant result normalization — CURRENT

Canonical implementation:

```text
experiments/gate0d/provider_result.py
experiments/gate0d/test_provider_result.py
```

0D-2 deliberately does **not** guess raw WeChat errcode mappings. A concrete WeChat adapter must first classify a real provider response into one normalized outcome. Exact raw-code mapping belongs to real-provider evidence and must be based on current official documentation / observed responses.

Normalized outcomes:

```text
SENT
USER_REJECTED
GRANT_INVALID
AUTH_REQUIRED
TEMPLATE_INVALID
RATE_LIMITED
NETWORK_ERROR
PROVIDER_ERROR
```

Normalized output freezes these independent facts:

```text
success
terminal_for_delivery
retryable
retry_class
grant_effect
provider_code/provider_message diagnostics
retry_after_seconds
```

Retry classes:

```text
NONE
TRANSIENT
AFTER_AUTH
AFTER_COOLDOWN
AFTER_CONFIG_FIX
```

Grant effects:

```text
KEEP
CONSUME
MARK_DENIED
MARK_EXHAUSTED
```

Current semantic table:

```text
SENT             -> success, terminal, no retry, CONSUME
USER_REJECTED    -> terminal failure, no retry, MARK_DENIED
GRANT_INVALID    -> terminal failure, no retry, MARK_EXHAUSTED
AUTH_REQUIRED    -> retry only after auth refresh, KEEP grant
TEMPLATE_INVALID -> blocked until config fix, KEEP grant
RATE_LIMITED     -> retry after cooldown, KEEP grant
NETWORK_ERROR    -> transient retryable, KEEP grant
PROVIDER_ERROR   -> transient retryable at this boundary, KEEP grant
```

0D-3 will apply attempt budgets / scheduling and decide when repeated transient errors become terminal. 0D-2 only normalizes one provider attempt.

### 0D-2 acceptance targets

```text
01 SENT is terminal success and consumes current grant          PENDING
02 USER_REJECTED marks grant denied                             PENDING
03 GRANT_INVALID marks grant exhausted                          PENDING
04 AUTH_REQUIRED requires auth refresh                          PENDING
05 TEMPLATE_INVALID waits for configuration fix                 PENDING
06 RATE_LIMITED requires cooldown                               PENDING
07 NETWORK_ERROR is transient retryable                         PENDING
08 PROVIDER_ERROR is transient retryable at this boundary       PENDING
09 retryable failure preserves user grant truth                 PENDING
10 template invalid preserves user grant truth                  PENDING
11 provider diagnostics are preserved                           PENDING
12 identical input normalizes deterministically                 PENDING
13 negative retry-after rejected                                PENDING
14 SENT cannot carry retry-after                                PENDING
15 terminal user/grant failures cannot carry retry-after        PENDING
16 result contract exposes no creator live-state fields         PENDING
17 auth failure does not revoke user grant                      PENDING
18 success/failure semantics are explicit                       PENDING
```

---

## Gate 0D-3 — Retry / terminal-failure semantics — NOT STARTED

0D-3 will compose `NotificationDelivery + NormalizedProviderResult` and freeze attempt history, bounded retry budgets, cooldown scheduling, terminal delivery states and restart safety. It must not duplicate logical deliveries and must never mutate Gate 0B live truth.

## Gate 0D-4 — Real WeChat acceptance evidence — NOT STARTED

Real WeChat evidence must verify current provider response mapping, user grant behavior and at least one real delivery path. Production/provider facts must not be inferred from this deterministic model.

## Progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  PASS
Gate 0D-2  CURRENT
Gate 0D    IN PROGRESS
Gate 0E    NOT STARTED
```
