# Gate 0E — End-to-End Golden Path

Status: **IN PROGRESS**

## Purpose

Gate 0E proves that the independently accepted Gate 0B/0C/0D semantics compose into one Stage Letter V0.1 golden path without creating a new hidden truth layer.

Canonical path:

```text
platform/source observation
  -> Gate 0C source composition
  -> canonical LiveObservation
  -> Gate 0B persistent State Engine
  -> LiveSession
  -> LIVE_STARTED LiveEvent
  -> Gate 0D eligibility
  -> logical NotificationDelivery
  -> Gate 0D delivery runtime
  -> provider result / real WeChat handoff
```

Permanent boundaries remain:

```text
UNKNOWN != OFFLINE
BOOTSTRAP_LIVE != real transition
notification/provider failure != creator live truth
same logical NotificationDelivery is locally idempotent
external provider exactly-once is not claimed
crash-after-send/before-response -> AMBIGUOUS -> no blind resend
```

## Gate plan

```text
0E-1 Deterministic cross-gate golden path        CURRENT
0E-2 Real provider handoff from golden event     NOT STARTED
Gate 0E                                           IN PROGRESS
```

---

## Gate 0E-1 — Deterministic cross-gate golden path — CURRENT

Canonical implementation:

```text
experiments/gate0e/golden_path.py
experiments/gate0e/test_golden_path.py
```

The harness reuses, rather than copies, the accepted implementations from:

```text
Gate 0C source_composition.py
Gate 0B state_engine.py + sqlite_store.py
Gate 0D notification_truth.py
Gate 0D provider_result.py + delivery_retry.py
```

### Acceptance matrix

```text
01 OFFLINE -> LIVE -> LIVE emits TRANSITION LIVE_STARTED           PENDING
02 transition creates exactly one eligible logical delivery       PENDING
03 SENT terminates delivery without inferred global exhaustion    PENDING
04 duplicate source replay creates no second delivery             PENDING
05 BOOTSTRAP_LIVE opens session but never notifies                PENDING
06 UNKNOWN source failure never closes a live session             PENDING
07 cross-source conflict -> UNKNOWN and keeps session open        PENDING
08 two explicit OFFLINE observations close session, no new notify PENDING
09 persistent state survives process restart                      PENDING
10 delivery-ledger snapshot preserves logical idempotency         PENDING
11 crash after begin/before response -> AMBIGUOUS / no blind send PENDING
12 provider network failure never mutates creator live truth      PENDING
13 notification context preserves title/live_url/source start     PENDING
14 non-GRANTED target never enters delivery runtime               PENDING
15 event/delivery identity is deterministic                       PENDING
```

Required acceptance:

```text
15/15 PASS
```

No test is allowed to manufacture a second canonical implementation of source arbitration, live state, eligibility, retry, or grant semantics merely to make the integration pass.

### Golden happy path

Expected deterministic path:

```text
StreamGet OFFLINE
  -> OFFLINE_CONFIRMED

StreamGet LIVE #1
  -> LIVE_PENDING

StreamGet LIVE #2
  -> LIVE_CONFIRMED
  -> LiveSession(origin=TRANSITION)
  -> LIVE_STARTED(cause=TRANSITION)
  -> eligible Follow + NotificationPreference + GRANTED
  -> exactly one NotificationDelivery
  -> IN_FLIGHT
  -> normalized SENT
  -> delivery SENT
```

The notification context must retain current composed metadata needed by V0.1, including title, live-room URL and trusted `source_started_at` when present.

---

## Gate 0E-2 — Real provider handoff from golden event — NOT STARTED

0E-2 will not repeat Gate 0D's provider experiments for their own sake. Gate 0D already proved:

```text
real wx.requestSubscribeMessage accept
real provider errcode=0
real phone receipt
SENT != proven global grant exhaustion
exact same provider payload can create two messages
no payload-based provider deduplication guarantee
```

0E-2 must instead prove one narrower integration fact:

```text
an eligible LIVE_STARTED event produced by the Gate 0E pipeline
  -> creates the exact logical delivery chosen for sending
  -> builds the real Stage Letter message payload
  -> crosses the already-proven WeChat provider boundary once
  -> intended account visibly receives the corresponding notification
```

The real send must be operator-triggered and secret-safe. It must not weaken the Gate 0D `AMBIGUOUS` crash rule or create a blind retry path.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E-1  CURRENT
Gate 0E-2  NOT STARTED
Gate 0E    IN PROGRESS
```

After Gate 0E PASS, proceed to formal V0.1 engineering / Gate 1.
