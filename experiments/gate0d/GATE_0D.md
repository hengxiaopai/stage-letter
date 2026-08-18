# Gate 0D — WeChat Notification Truth

Status: **DEGRADED / REAL EVIDENCE COMPLETION IN PROGRESS**

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
0D-4 Real WeChat acceptance evidence              DEGRADED / PARTIAL PASS
```

Real provider evidence corrected one earlier deterministic assumption: `SENT` cannot be treated as proof that the user's provider-side grant inventory is globally exhausted. The implementation/tests were corrected and the complete 54-test deterministic suite was rerun successfully on 2026-08-18.

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

Acceptance: **PASS 16/16**.

---

## Gate 0D-2 — Provider / grant result normalization — PASS

Canonical implementation:

```text
experiments/gate0d/provider_result.py
experiments/gate0d/test_provider_result.py
```

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

Corrected deterministic revalidation:

```text
Gate 0D complete deterministic suite: 54/54 PASS
Provider-result subset: 18/18 PASS
```

Acceptance: **PASS 18/18**.

---

## Gate 0D-3 — Retry / terminal-failure semantics — PASS

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

The corrected delivery invariant is:

```text
SENT
  -> terminal for this NotificationDelivery
  -> cannot send this same logical delivery again
  -> does not imply global GrantState.EXHAUSTED
```

Corrected deterministic revalidation:

```text
Gate 0D complete deterministic suite: 54/54 PASS
Retry/runtime subset: 20/20 PASS
```

Acceptance: **PASS 20/20**.

---

## Gate 0D-4 — Real WeChat acceptance evidence — DEGRADED / PARTIAL PASS

Canonical experiment/evidence assets:

```text
experiments/gate0d/REAL_WECHAT.md
experiments/gate0d/REAL_WECHAT_20260818.md
experiments/gate0d/real_wechat_probe.py
experiments/gate0d/real_wechat_replay_probe.py
experiments/gate0d/wechat-real-demo/
```

### Confirmed real facts

Real client subscription callback:

```json
{
  "callback": "success",
  "errMsg": "requestSubscribeMessage:ok",
  "templateResult": "accept"
}
```

Two real service-side sends were observed for the same app/template/openid fingerprints:

```text
send #1  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:02
send #2  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:10
```

The controlled sequence did not intentionally call `wx.requestSubscribeMessage` between those two ordinary sends.

This confirms:

```text
A. exact client wx.requestSubscribeMessage result  PASS / accept
B. real provider response captured                 PASS
C. real errcode=0 send                             PASS (two sends)
D. corresponding phone receipt                     PASS (two receipts)
E. post-send grant behavior observed               PASS / SENT != proven EXHAUSTED
H. no secret material in canonical evidence        PASS
```

Still open:

```text
F. exact duplicate/replay/idempotency boundary     CURRENT
G. evidence-backed non-zero errcode mappings       OPEN
```

### Exact replay experiment

`real_wechat_replay_probe.py` performs exactly two provider calls in one process with:

```text
same access token
same openid
same template id
same template data
same page/miniprogram_state/lang
same request-body fingerprint
```

Only fingerprints and sanitized provider responses are persisted. The operator must also record whether the phone receives zero, one or two corresponding notifications.

Until exact replay evidence proves otherwise, the deterministic safety rule remains mandatory:

```text
IN_FLIGHT at crash/restart
  -> AMBIGUOUS
  -> no blind automatic resend
```

---

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  PASS
Gate 0D-2  PASS
Gate 0D-3  PASS
Gate 0D-4  DEGRADED / real evidence partial
Gate 0D    DEGRADED
Gate 0E    NOT STARTED
```

Next real-evidence priority:

```text
F. run one controlled exact-payload replay and record provider responses + phone receipt count
G. preserve any non-zero errcode as unmapped unless evidence supports classification
```
