# Gate 0D-4 — Real WeChat Acceptance Evidence

Status: **PASS / REAL-PROVIDER ACCEPTANCE CAPTURED**

## Purpose

Gate 0D-4 is the only Gate 0D stage allowed to claim real WeChat provider behavior. The deterministic models from 0D-1/0D-2/0D-3 are necessary but not sufficient for:

- real client subscription grant results;
- real provider `errcode` / `errmsg` behavior;
- real post-send grant behavior;
- real message receipt on a phone;
- provider-side replay/idempotency behavior.

The completed sanitized evidence record is:

```text
experiments/gate0d/REAL_WECHAT_20260818.md
```

Gate 0D-4 and Gate 0D are now **PASS**.

## Safety rules

```text
never commit AppSecret
never commit access_token
never commit session_key
never commit a fresh wx.login code
never print/persist access_token or session_key
non-zero provider errcode is not guessed into a domain outcome
```

The probes persist only fingerprints and sanitized provider facts.

## Components

```text
experiments/gate0d/wechat-real-demo/
    minimal client probe for wx.requestSubscribeMessage + wx.login

experiments/gate0d/real_wechat_probe.py
    real service-side code2session / access-token / subscribe-message send probe

experiments/gate0d/real_wechat_replay_probe.py
    controlled two-call exact-payload replay probe
```

## Conservative provider mapping

The real probe intentionally maps only:

```text
errcode == 0                -> SENT
transport failure           -> NETWORK_ERROR
any other provider response -> UNMAPPED_PROVIDER_ERROR
```

A non-zero WeChat `errcode` is not promoted to `USER_REJECTED`, `GRANT_INVALID`, `AUTH_REQUIRED`, `TEMPLATE_INVALID`, `RATE_LIMITED`, or another more specific domain outcome until current documentation and/or direct observed evidence supports that exact classification.

## Captured PASS evidence

```text
A. real client requestSubscribeMessage callback: success / accept       PASS
B. real provider send response captured                                 PASS
C. real errcode=0 sends                                                  PASS
D. intended WeChat account visibly received notifications                PASS
E. post-send grant behavior observed; SENT != proven global exhaustion   PASS
F. exact same-payload replay boundary captured                           PASS
G. non-zero raw codes remain evidence-gated / conservative               PASS
H. no secret material persisted in canonical evidence                    PASS
```

## Exactly-once limitation

The controlled exact replay used the same access token and same request-body fingerprint for two consecutive provider calls. Both returned `errcode=0`, returned distinct `msgid` values, and produced two visible phone notifications.

Therefore Stage Letter cannot rely on payload equality for provider deduplication. The Gate 0D-3 crash rule is permanently retained:

```text
IN_FLIGHT at process crash
    -> AMBIGUOUS
    -> no blind automatic resend
```

Stage Letter claims local logical-delivery idempotency, not provider-backed exactly-once external delivery.

## Evidence handling

Raw probe evidence is written under:

```text
experiments/gate0d/data/
```

That directory remains local/gitignored. Only sanitized facts required for Gate decisions are promoted to canonical evidence documents.