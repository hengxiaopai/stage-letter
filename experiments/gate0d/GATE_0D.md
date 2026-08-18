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
0D-1 Eligibility + logical delivery idempotency   CURRENT
0D-2 Provider/grant result normalization          NEXT
0D-3 Retry / terminal-failure semantics           NOT STARTED
0D-4 Real WeChat acceptance evidence              NOT STARTED
```

---

## Gate 0D-1 — Eligibility + delivery idempotency

Canonical implementation:

```text
experiments/gate0d/notification_truth.py
experiments/gate0d/test_notification_truth.py
```

### Eligibility truth

A notification is eligible only when all of the following are true:

```text
event.type  == LIVE_STARTED
event.cause == TRANSITION
Follow       == true
NotificationPreference.enabled == true
WeChat grant state == GRANTED
```

Therefore:

```text
BOOTSTRAP_LIVE != a proven new start -> no live-start notification
LIVE_ENDED -> no live-start notification
not following -> no delivery
preference disabled -> no delivery
grant DENIED / UNKNOWN / EXHAUSTED -> no delivery
```

The grant is a channel/provider fact. It is not encoded into Follow or creator live state.

### Delivery identity

Logical delivery uniqueness is frozen as:

```text
(user_id, live_event_id, channel)
```

Re-evaluating the same eligible user/event/channel must return the same logical delivery rather than create another.

Different users for the same event are separate deliveries. Different live events for the same user are separate deliveries.

### Current delivery state

0D-1 stops before provider sending. An eligible logical delivery enters as:

```text
PENDING
```

Provider outcomes, retryability, grant consumption/invalidity and terminal failures belong to 0D-2/0D-3 and are intentionally not guessed here.

### Safety boundary

`DeliveryLedger` has no API for opening/closing LiveSession or changing creator LIVE/OFFLINE state.

---

## 0D-1 acceptance matrix

```text
01 transition LIVE_STARTED is eligible                         PENDING CI
02 BOOTSTRAP_LIVE is not eligible                              PENDING CI
03 LIVE_ENDED is not eligible                                  PENDING CI
04 not-following target is not eligible                        PENDING CI
05 disabled notification preference is not eligible            PENDING CI
06 denied grant is not eligible                                PENDING CI
07 unknown/exhausted grant is not eligible                     PENDING CI
08 eligible decision creates one PENDING delivery              PENDING CI
09 same user/event/channel is idempotent                       PENDING CI
10 ineligible decision creates no delivery                     PENDING CI
11 same event for different users creates separate deliveries  PENDING CI
12 different events for one user create separate deliveries    PENDING CI
13 restart snapshot preserves delivery idempotency              PENDING CI
14 account identity mismatch rejected                          PENDING CI
15 invalid identities rejected                                 PENDING CI
16 notification truth exposes no live-state mutation API        PENDING CI
```

## Next: Gate 0D-2

After 0D-1 passes, define and test provider/grant result normalization without yet claiming real WeChat delivery success. Candidate normalized outcomes must distinguish at least:

```text
SENT
USER_REJECTED / GRANT_INVALID
AUTH_REQUIRED
TEMPLATE_INVALID
RATE_LIMITED
NETWORK_ERROR
PROVIDER_ERROR
```

Retryability must be explicit, and no provider outcome may alter Gate 0B creator state.

## Progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D-1  IN PROGRESS
Gate 0D    IN PROGRESS
Gate 0E    NOT STARTED
```
