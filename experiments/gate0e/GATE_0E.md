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
0E-1 Deterministic cross-gate golden path        PASS 15/15
0E-2 Real provider handoff from golden event     CURRENT
Gate 0E                                           IN PROGRESS
```

---

## Gate 0E-1 — Deterministic cross-gate golden path — PASS

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
01 OFFLINE -> LIVE -> LIVE emits TRANSITION LIVE_STARTED           PASS
02 transition creates exactly one eligible logical delivery       PASS
03 SENT terminates delivery without inferred global exhaustion    PASS
04 duplicate source replay creates no second delivery             PASS
05 BOOTSTRAP_LIVE opens session but never notifies                PASS
06 UNKNOWN source failure never closes a live session             PASS
07 cross-source conflict -> UNKNOWN and keeps session open        PASS
08 two explicit OFFLINE observations close session, no new notify PASS
09 persistent state survives process restart                      PASS
10 delivery-ledger snapshot preserves logical idempotency         PASS
11 crash after begin/before response -> AMBIGUOUS / no blind send PASS
12 provider network failure never mutates creator live truth      PASS
13 notification context preserves title/live_url/source start     PASS
14 non-GRANTED target never enters delivery runtime               PASS
15 event/delivery identity is deterministic                       PASS
```

Local acceptance evidence on 2026-08-18:

```text
Ran 15 tests in 1.366s
OK
```

Acceptance: **PASS 15/15**.

### Frozen deterministic happy path

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

The notification context retains title, live-room URL and trusted `source_started_at` when present.

---

## Gate 0E-2 — Real provider handoff from golden event — CURRENT

Canonical operator harness:

```text
experiments/gate0e/real_golden_handoff.py
```

0E-2 does not repeat Gate 0D's provider experiments for their own sake. Gate 0D already proved:

```text
real wx.requestSubscribeMessage accept
real provider errcode=0
real phone receipt
SENT != proven global grant exhaustion
exact same provider payload can create two messages
no payload-based provider deduplication guarantee
```

0E-2 proves one narrower integration fact:

```text
controlled OFFLINE -> LIVE -> LIVE source sequence
  -> Gate 0C composition
  -> Gate 0B TRANSITION LIVE_STARTED
  -> Gate 0D eligible logical NotificationDelivery
  -> Stage Letter live-start payload built from the preserved event context
  -> delivery runtime enters IN_FLIGHT before provider send
  -> exactly one real WeChat provider call
  -> provider result is applied to that exact logical delivery
  -> intended account visibly receives the corresponding notification
```

The source-side transition remains a controlled Gate harness rather than a claim that Gate 0A's deferred real lifecycle evidence gap has disappeared.

### Safety rules

```text
provider send count = exactly 1 per operator run
IN_FLIGHT is recorded before the external side effect
no blind retry exists in the operator tool
non-zero provider codes remain conservative/unmapped
AppSecret/access_token/session_key/login-code/raw-openid are not persisted
rerunning the operator manually is a new external send and can duplicate a message
```

### Current verified template defaults

The operator defaults to the currently verified live-start template field mapping:

```text
thing1 -> 直播间名称
thing2 -> 达人名称
time3  -> 开播时间
thing5 -> 直播主题
thing6 -> 直播间活动
```

These field names are operator-overridable if the WeChat template changes.

### Operator procedure

1. Sync the repository.
2. Do **not** request another subscription grant if the existing accepted grant is intentionally being used for this handoff.
3. Obtain one fresh `wx.login` code immediately before the run.
4. Run a dry validation first:

```bash
./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0e/real_golden_handoff.py \
  --creator-name "珩小派" \
  --room-name "开场信 Gate 0E Golden Path" \
  --activity "Gate 0E 真实链路验证" \
  --title "爱播开播啦 · Gate 0E" \
  --live-url "https://live.douyin.com/gate0e"
```

5. Then perform the single real handoff:

```bash
./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0e/real_golden_handoff.py \
  --login-code "FRESH_WX_LOGIN_CODE" \
  --creator-name "珩小派" \
  --room-name "开场信 Gate 0E Golden Path" \
  --activity "Gate 0E 真实链路验证" \
  --title "爱播开播啦 · Gate 0E" \
  --live-url "https://live.douyin.com/gate0e" \
  --send
```

AppID, AppSecret and template ID may come from the already-established local `WECHAT_*` environment variables. AppSecret is prompted without echo if not present in the environment.

### Required 0E-2 PASS evidence

```text
A. source transition is OFFLINE -> LIVE -> LIVE
B. emitted event is exactly LIVE_STARTED / TRANSITION
C. exactly one eligible logical NotificationDelivery is selected
D. payload is built from the preserved GoldenPath notification context
E. runtime state is IN_FLIGHT before provider send
F. provider_send_count == 1
G. real provider result is errcode=0 / SENT
H. runtime finishes SENT for that exact delivery
I. intended WeChat account visibly receives the corresponding message
J. canonical evidence contains no secret material
```

Required acceptance: **10/10 PASS**.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E-1  PASS 15/15
Gate 0E-2  CURRENT
Gate 0E    IN PROGRESS
```

After Gate 0E PASS, proceed to formal V0.1 engineering / Gate 1.
