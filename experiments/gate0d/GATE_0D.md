# Gate 0D — WeChat Notification Truth

Status: **DEGRADED / REAL EVIDENCE REFINEMENT IN PROGRESS**

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
0D-2 Provider/grant result normalization          DEGRADED / REVALIDATION REQUIRED
0D-3 Retry / terminal-failure semantics           DEGRADED / REVALIDATION REQUIRED
0D-4 Real WeChat acceptance evidence              DEGRADED / PARTIAL PASS
```

The earlier 0D-2/0D-3 deterministic runs passed their then-current assertions, but subsequent real provider evidence disproved one assumption: `SENT` cannot be treated as proof that the user's provider-side grant inventory is globally exhausted. The implementation and tests have been corrected and must be rerun before 0D-2/0D-3 return to PASS.

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

Clean local acceptance evidence:

```text
Ran 16 tests in 0.003s
OK
```

Acceptance: **PASS 16/16**.

---

## Gate 0D-2 — Provider / grant result normalization — DEGRADED / REVALIDATION REQUIRED

Canonical implementation:

```text
experiments/gate0d/provider_result.py
experiments/gate0d/test_provider_result.py
```

Normalized outcomes remain:

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

Normalized facts remain independent:

```text
success
terminal_for_delivery
retryable
retry_class
grant_effect
provider diagnostics
retry_after_seconds
```

### Real-provider correction

The original deterministic rule treated successful send as:

```text
SENT -> CONSUME -> GrantState.EXHAUSTED
```

Gate 0D-4 then produced two consecutive real `errcode=0` sends to the same openid fingerprint, with two visible phone receipts, without an intentionally repeated subscription request between those two sends.

Therefore a successful send proves only that one send entitlement was used. It does **not** prove that no additional entitlement remains when exact provider-side grant balance is unknown.

Corrected semantics:

```text
SENT
  -> success
  -> terminal for this logical delivery
  -> grant_effect = CONSUME_ONE
  -> do not infer EXHAUSTED

GRANT_INVALID / explicit exhaustion evidence
  -> may mark GrantState.EXHAUSTED
```

Other semantic rows remain:

```text
USER_REJECTED    -> terminal failure, MARK_DENIED
AUTH_REQUIRED    -> AFTER_AUTH, KEEP
TEMPLATE_INVALID -> AFTER_CONFIG_FIX, KEEP
RATE_LIMITED     -> AFTER_COOLDOWN, KEEP
NETWORK_ERROR    -> TRANSIENT, KEEP
PROVIDER_ERROR   -> TRANSIENT at this boundary, KEEP
```

The previous 18/18 local PASS is superseded by this semantic correction. Revalidation is required.

---

## Gate 0D-3 — Retry / terminal-failure semantics — DEGRADED / REVALIDATION REQUIRED

Canonical implementation:

```text
experiments/gate0d/delivery_retry.py
experiments/gate0d/test_delivery_retry.py
```

Execution states remain:

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

The crash-safety boundary is unchanged:

```text
IN_FLIGHT at restart
    -> AMBIGUOUS
    -> no blind automatic resend
```

Retry/backoff, auth/config blocking, attempt budgets, restart safety and duplicate completion replay remain unchanged.

The corrected delivery invariant is now:

```text
SENT
  -> terminal for this NotificationDelivery
  -> cannot send this same logical delivery again
  -> does not imply global GrantState.EXHAUSTED
```

The previous 20/20 local PASS is superseded only for the affected grant assertion; the complete suite must rerun before 0D-3 returns to PASS.

---

## Gate 0D-4 — Real WeChat acceptance evidence — DEGRADED / PARTIAL PASS

Canonical experiment/evidence assets:

```text
experiments/gate0d/REAL_WECHAT.md
experiments/gate0d/REAL_WECHAT_20260818.md
experiments/gate0d/real_wechat_probe.py
experiments/gate0d/wechat-real-demo/
```

### Confirmed real facts

Two real service-side sends were observed for the same app/template/openid fingerprints:

```text
send #1  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:02
send #2  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:10
```

The controlled sequence did not intentionally call `wx.requestSubscribeMessage` between the two sends.

This confirms:

```text
B. real provider response captured                 PASS
C. real errcode=0 send                             PASS (two sends)
D. corresponding phone receipt                     PASS (two receipts)
E. post-send grant behavior observed               PASS / SENT != proven EXHAUSTED
H. no secret material in canonical evidence        PASS
```

Still open:

```text
A. exact client wx.requestSubscribeMessage result  OPEN
F. exact duplicate/replay/idempotency boundary     OPEN
G. evidence-backed non-zero errcode mappings       OPEN
```

Two successful sends are **not** evidence of provider-side request idempotency. The `AMBIGUOUS` crash rule therefore remains mandatory.

---

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  PASS
Gate 0D-2  DEGRADED / corrected; revalidation pending
Gate 0D-3  DEGRADED / corrected; revalidation pending
Gate 0D-4  DEGRADED / real evidence partial
Gate 0D    DEGRADED
Gate 0E    NOT STARTED
```

Next deterministic acceptance command after local merge state is clean:

```bash
python -m unittest discover -s experiments/gate0d -p "test_*.py" -v
```

Expected count remains 54 tests. After 54/54 passes with the corrected grant semantics, 0D-2 and 0D-3 may return to PASS; 0D-4 will still require client grant-result and duplicate/replay evidence before Gate 0D can close.
