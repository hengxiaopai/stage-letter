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
0D-2 Provider/grant result normalization          PASS
0D-3 Retry / terminal-failure semantics           CURRENT
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

---

## Gate 0D-2 — Provider / grant result normalization — PASS

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

Semantic table:

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

Clean local combined acceptance evidence on 2026-08-18:

```text
Ran 34 tests in 0.005s
OK
```

The 18 provider-result tests all passed, so 0D-2 is **PASS 18/18**. Together with 0D-1 the Gate 0D deterministic suite was **34/34 PASS** at this checkpoint.

---

## Gate 0D-3 — Retry / terminal-failure semantics — CURRENT

Canonical implementation:

```text
experiments/gate0d/delivery_retry.py
experiments/gate0d/test_delivery_retry.py
```

0D-3 composes one logical `NotificationDelivery` with normalized provider results and freezes the execution lifecycle:

```text
PENDING
  -> IN_FLIGHT
  -> SENT
  -> FAILED_TERMINAL
  -> WAITING_RETRY
  -> WAITING_AUTH
  -> BLOCKED_CONFIG
  -> AMBIGUOUS
```

### Persist-before-send boundary

An attempt must enter `IN_FLIGHT` before the external provider call. This is essential because an external send is not part of the local database transaction.

If the process restarts while an attempt is still `IN_FLIGHT`, the result is:

```text
IN_FLIGHT at crash/restart
    -> AMBIGUOUS
    -> no blind automatic retry
```

Without a provider-side idempotency/reconciliation guarantee, the system cannot know whether the provider accepted the request before the crash. Blindly retrying could duplicate a notification. Gate 0D therefore refuses to claim exactly-once external delivery semantics that the provider has not proven.

### Retry policy

Gate acceptance defaults are test parameters, not frozen production SLA values:

```text
max_total_attempts                = 5
transient_base_delay_seconds     = 30
transient_max_delay_seconds      = 600
default_cooldown_seconds         = 300
```

Rules:

```text
SENT
    -> terminal success
    -> grant consumed
    -> never send again

USER_REJECTED / GRANT_INVALID
    -> FAILED_TERMINAL
    -> no automatic retry

NETWORK_ERROR / PROVIDER_ERROR
    -> WAITING_RETRY
    -> bounded exponential backoff
    -> total-attempt budget enforced

RATE_LIMITED
    -> WAITING_RETRY
    -> provider retry_after_seconds when present
    -> otherwise default cooldown

AUTH_REQUIRED
    -> WAITING_AUTH
    -> no time-based blind retry
    -> explicit auth-refresh resume required

TEMPLATE_INVALID
    -> BLOCKED_CONFIG
    -> explicit config-fix resume required
```

Provider attempt IDs are unique within one logical delivery runtime. Completion replay with the same normalized outcome is idempotent; conflicting replay is rejected.

Restart snapshots preserve attempt history, grant truth and retry schedule. A restart during a resolved WAITING_RETRY remains WAITING_RETRY; a restart during unresolved IN_FLIGHT becomes AMBIGUOUS.

### 0D-3 acceptance targets

```text
01 begin attempt persists IN_FLIGHT before send                  PENDING
02 SENT is terminal and consumes grant                           PENDING
03 SENT delivery cannot send again                               PENDING
04 USER_REJECTED -> terminal + denied grant                      PENDING
05 GRANT_INVALID -> terminal + exhausted grant                   PENDING
06 NETWORK_ERROR schedules transient retry                       PENDING
07 transient retry backoff grows exponentially                   PENDING
08 transient backoff respects cap                                PENDING
09 RATE_LIMITED honors provider retry-after                      PENDING
10 missing retry-after uses default cooldown                     PENDING
11 AUTH_REQUIRED waits for explicit auth resume                  PENDING
12 auth resume preserves grant and allows new attempt            PENDING
13 TEMPLATE_INVALID waits for explicit config fix                PENDING
14 total attempt budget makes repeated transient failure terminal PENDING
15 restart preserves waiting-retry schedule/history              PENDING
16 restart with IN_FLIGHT -> AMBIGUOUS / no blind retry          PENDING
17 duplicate completion replay is idempotent                     PENDING
18 retry cannot start before due time                            PENDING
19 attempt IDs are unique within one logical delivery            PENDING
20 runtime exposes no creator live-state fields                  PENDING
```

---

## Gate 0D-4 — Real WeChat acceptance evidence — NOT STARTED

Real WeChat evidence must verify current raw provider-response mapping, user grant behavior and at least one real delivery path. Production/provider facts must not be inferred from the deterministic model.

0D-4 must also determine what, if any, provider-side idempotency or reconciliation facility exists for subscription-message sends. Until then, `AMBIGUOUS` remains a required safety state for crash-after-send/before-response scenarios.

## Progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  PASS
Gate 0D-2  PASS
Gate 0D-3  CURRENT
Gate 0D    IN PROGRESS
Gate 0E    NOT STARTED
```
