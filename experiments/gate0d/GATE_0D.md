# Gate 0D — WeChat Notification Truth

Status: **PASS**

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
0D-4 Real WeChat acceptance evidence              PASS
```

The deterministic model was corrected after real-provider evidence showed that `SENT` does not prove global provider-side grant exhaustion. The corrected complete deterministic suite was rerun successfully: **54/54 PASS**.

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

Acceptance: **PASS 16/16**.

---

## Gate 0D-2 — Provider / grant result normalization — PASS

Canonical implementation:

```text
experiments/gate0d/provider_result.py
experiments/gate0d/test_provider_result.py
```

Corrected successful-send semantics:

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

Crash-safety boundary:

```text
IN_FLIGHT at restart
    -> AMBIGUOUS
    -> no blind automatic resend
```

Corrected delivery invariant:

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

## Gate 0D-4 — Real WeChat acceptance evidence — PASS

Canonical assets:

```text
experiments/gate0d/REAL_WECHAT.md
experiments/gate0d/REAL_WECHAT_20260818.md
experiments/gate0d/real_wechat_probe.py
experiments/gate0d/real_wechat_replay_probe.py
experiments/gate0d/wechat-real-demo/
```

### A. Real client subscription result — PASS

Observed callback:

```json
{
  "callback": "success",
  "errMsg": "requestSubscribeMessage:ok",
  "templateResult": "accept"
}
```

### B/C/D. Real provider send and phone receipt — PASS

Two ordinary real sends were observed for the same app/template/openid fingerprints:

```text
send #1  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:02
send #2  errcode=0 / errmsg=ok / normalized=SENT / phone receipt confirmed ~15:10
```

### E. Post-send grant behavior — PASS

Real evidence demonstrated:

```text
SENT != proven global grant exhaustion
```

The model was corrected accordingly and the complete deterministic suite returned **54/54 PASS**.

### F. Exact replay / provider idempotency boundary — PASS

Controlled experiment:

```text
experiment                    EXACT_PAYLOAD_REPLAY
replay_count                  2
same_access_token_for_both    true
openid_fingerprint            cbdafe5eb1a0ea94
request_payload_fingerprint   9e040003c7649066

attempt #1  errcode=0 / errmsg=ok / msgid=4654832376731369477
attempt #2  errcode=0 / errmsg=ok / msgid=4654832384247562248
phone receipt count: 2
```

Both exact same-payload calls were accepted independently, returned distinct `msgid` values, and produced two visible corresponding notifications. Under the tested path, no automatic provider deduplication was observed.

Therefore Stage Letter must not rely on payload equality for provider idempotency and must preserve:

```text
IN_FLIGHT at crash/restart
  -> AMBIGUOUS
  -> no blind automatic resend
```

External exactly-once delivery is not claimed.

### G. Non-zero raw provider mapping discipline — PASS

The real probe freezes conservative mapping:

```text
errcode == 0                -> SENT
transport failure           -> NETWORK_ERROR
other non-zero provider     -> UNMAPPED_PROVIDER_ERROR
```

Non-zero raw WeChat codes are not promoted to `USER_REJECTED`, `GRANT_INVALID`, `AUTH_REQUIRED`, `TEMPLATE_INVALID`, `RATE_LIMITED`, or other specific domain outcomes without current documentation and/or direct observed evidence for that exact mapping.

A real pre-send credential failure was observed earlier at `code2session` (`errcode=40125`, provider response reporting an invalid AppSecret). It remained a credential-layer failure and was not misclassified as user grant or notification-delivery truth.

### H. Secret handling — PASS

Canonical evidence persists no AppSecret, access token, session key, fresh login code, or raw openid. Raw local evidence remains gitignored.

### 0D-4 acceptance matrix

```text
A client subscription result                         PASS
B real provider response                            PASS
C real errcode=0 send                               PASS
D intended account visibly received                 PASS
E post-send grant behavior                          PASS
F exact replay / idempotency boundary               PASS
G non-zero mapping discipline                       PASS
H no secret material persisted                      PASS
--------------------------------------------------------
Gate 0D-4                                            PASS
```

---

## Gate 0D final decision

```text
Gate 0D-1  PASS
Gate 0D-2  PASS
Gate 0D-3  PASS
Gate 0D-4  PASS
----------------
Gate 0D    PASS
```

Permanent safety conclusions:

```text
UNKNOWN notification/provider truth never mutates creator live truth
successful send does not prove global grant exhaustion
same logical NotificationDelivery is locally idempotent
exact same provider payload may produce duplicate external notifications
crash-after-send/before-response -> AMBIGUOUS -> no blind resend
no provider-backed exactly-once claim
non-zero provider codes remain conservative until evidence-backed
```

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E    NOT STARTED
```

Next gate: **Gate 0E — End-to-End Golden Path**.