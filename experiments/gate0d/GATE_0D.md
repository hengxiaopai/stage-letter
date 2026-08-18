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
    -> retry / terminal execution
    -> real WeChat evidence

notification failure != creator OFFLINE
notification failure != LiveSession mutation
```

## Gate plan

```text
0D-1 Eligibility + logical delivery idempotency   PASS 16/16
0D-2 Provider/grant result normalization          PASS 18/18
0D-3 Retry / terminal-failure semantics           PASS 20/20
0D-4 Real WeChat acceptance evidence              CURRENT
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

0D-2 freezes provider-agnostic normalized outcomes without guessing raw WeChat non-zero errcode mappings:

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

Normalized facts are independent:

```text
success
terminal_for_delivery
retryable
retry_class
grant_effect
provider diagnostics
retry_after_seconds
```

Semantic table:

```text
SENT             -> terminal success, CONSUME
USER_REJECTED    -> terminal failure, MARK_DENIED
GRANT_INVALID    -> terminal failure, MARK_EXHAUSTED
AUTH_REQUIRED    -> AFTER_AUTH, KEEP
TEMPLATE_INVALID -> AFTER_CONFIG_FIX, KEEP
RATE_LIMITED     -> AFTER_COOLDOWN, KEEP
NETWORK_ERROR    -> TRANSIENT, KEEP
PROVIDER_ERROR   -> TRANSIENT at this boundary, KEEP
```

Clean local combined evidence:

```text
Ran 34 tests in 0.005s
OK
```

0D-2 acceptance: **PASS 18/18**.

---

## Gate 0D-3 — Retry / terminal-failure semantics — PASS

Canonical implementation:

```text
experiments/gate0d/delivery_retry.py
experiments/gate0d/test_delivery_retry.py
```

Execution states:

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

### Persist-before-send boundary

Each provider attempt is recorded as `IN_FLIGHT` before the external send. If the process restarts while an unresolved attempt remains `IN_FLIGHT`, the runtime restores it as:

```text
IN_FLIGHT at restart
    -> AMBIGUOUS
    -> no blind automatic resend
```

This prevents a crash-after-send/before-response window from silently creating duplicate user notifications when provider-side idempotency/reconciliation has not been proven.

Gate acceptance retry parameters are configurable test values, not production SLA values:

```text
max_total_attempts                = 5
transient_base_delay_seconds     = 30
transient_max_delay_seconds      = 600
default_cooldown_seconds         = 300
```

Frozen behavior:

```text
SENT
    -> terminal
    -> grant consumed
    -> cannot send again

USER_REJECTED / GRANT_INVALID
    -> FAILED_TERMINAL

NETWORK_ERROR / PROVIDER_ERROR
    -> bounded exponential WAITING_RETRY

RATE_LIMITED
    -> WAITING_RETRY
    -> provider retry-after when supplied, otherwise default cooldown

AUTH_REQUIRED
    -> WAITING_AUTH
    -> explicit auth resume required

TEMPLATE_INVALID
    -> BLOCKED_CONFIG
    -> explicit config-fix resume required

attempt budget exhausted
    -> FAILED_TERMINAL
```

Restart snapshots preserve resolved attempt history, retry schedule, grant truth and idempotency. Duplicate completion replay with the same stored outcome is idempotent; conflicting replay is rejected.

Clean local acceptance evidence on 2026-08-18:

```text
Ran 54 tests in 0.011s
OK
```

The 20 retry/runtime tests all passed. Therefore:

```text
0D-1  16/16 PASS
0D-2  18/18 PASS
0D-3  20/20 PASS
------------------
Total  54/54 PASS
```

Gate 0D-3 acceptance: **PASS 20/20**.

---

## Gate 0D-4 — Real WeChat acceptance evidence — CURRENT

0D-4 is the only stage allowed to claim actual WeChat provider behavior.

Canonical experiment assets:

```text
experiments/gate0d/REAL_WECHAT.md
experiments/gate0d/real_wechat_probe.py
experiments/gate0d/wechat-real-demo/
```

The mini-program probe captures the real `wx.requestSubscribeMessage` result and a fresh `wx.login` code when needed. The service-side probe can exchange the login code for an openid, obtain an access token and perform one real subscription-message send while refusing to persist AppSecret, access_token, session_key, login code or raw openid.

The provider probe deliberately maps only:

```text
errcode == 0                -> SENT
transport failure           -> NETWORK_ERROR
other non-zero provider     -> UNMAPPED_PROVIDER_ERROR
```

Non-zero raw WeChat errors are not guessed into the 0D-2 taxonomy until real/current evidence supports the mapping.

Gate 0D-4 requires at least:

```text
1. real client subscription result captured
2. real provider response captured
3. at least one errcode=0 send
4. corresponding phone/account visibly receives the message
5. one-time grant behavior observed after successful send
6. duplicate/replay/provider-idempotency boundary documented
7. only evidence-backed non-zero errcode mappings accepted
8. no secret material persisted in repository evidence
```

Raw local evidence is written under `experiments/gate0d/data/` and is gitignored. Only sanitized facts should be promoted into canonical Gate evidence.

Until real provider evidence closes these items, Gate 0D remains **IN PROGRESS**.

---

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  PASS
Gate 0D-2  PASS
Gate 0D-3  PASS
Gate 0D-4  CURRENT
Gate 0D    IN PROGRESS
Gate 0E    NOT STARTED
```
