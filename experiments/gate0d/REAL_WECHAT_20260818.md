# Gate 0D-4 — Real WeChat Evidence — 2026-08-18

Status: **PARTIAL PASS / TWO REAL SENDS + TWO PHONE RECEIPTS CONFIRMED**

This sanitized record captures only non-secret facts from the real WeChat subscription-message experiment. Raw local JSON evidence remains under `experiments/gate0d/data/` and is gitignored.

## Real provider send #1

Observed service-side result:

```text
send_requested            true
appid_fingerprint         79f345434b4e9cd6
template_id_fingerprint   899f5861362c5315
openid_source             code2session
openid_fingerprint        cbdafe5eb1a0ea94
token_acquired            true
provider.errcode           0
provider.errmsg            ok
provider.normalized        SENT
provider_mapping_status    CONFIRMED_SENT
secrets_persisted          false
```

The intended WeChat account visibly received the corresponding service notification at approximately 15:02 local time.

Visible message facts included:

```text
notification title   直播开播通知
开播时间             2026-08-18 14:30
直播间活动           无
直播主题             开播啦
达人名称             X.四五六🍉
直播间名称           重生之我在传媒当歌手
```

## Real provider send #2

The controlled follow-up sequence did not intentionally call `wx.requestSubscribeMessage` between send #1 and send #2. A fresh `wx.login` code was obtained and the same configured app/template/openid path was used again.

Observed service-side result:

```text
captured_at             2026-08-18T07:10:12+00:00
send_requested          true
appid_fingerprint       79f345434b4e9cd6
template_id_fingerprint 899f5861362c5315
openid_source           code2session
openid_fingerprint      cbdafe5eb1a0ea94
token_acquired          true
provider.errcode         0
provider.errmsg          ok
provider.normalized      SENT
provider_mapping_status  CONFIRMED_SENT
secrets_persisted        false
```

The same intended WeChat account visibly received the second corresponding notification at approximately 15:10 local time.

Visible message facts included:

```text
notification title   直播开播通知
开播时间             2026-08-18 05:20
直播间活动           发1000W福袋
直播主题             君子如珩，取予有节
达人名称             珩小派
直播间名称           我在创作开场信小程序
```

## Important semantic finding

The second provider `errcode=0` send and second phone receipt are evidence that a successful send does **not** by itself prove that no further provider-side send entitlement remains for that user/template/account state.

The experiment does not know how many prior subscription grants may have been accumulated, so it cannot infer an exact remaining balance from these two sends. The earlier deterministic rule:

```text
SENT -> local GrantState.EXHAUSTED
```

is therefore too strong and has been superseded.

The corrected rule is:

```text
SENT
  -> terminal success for this logical NotificationDelivery
  -> one send entitlement was used
  -> DO NOT infer global grant exhaustion without explicit provider evidence

explicit grant-invalid/exhaustion evidence
  -> may mark local grant state EXHAUSTED
```

This correction reopens the affected 0D-2/0D-3 assertions for deterministic revalidation before those sub-gates can be considered closed again.

## Gate items confirmed

```text
B. real send provider response captured                 PASS
C. at least one real errcode=0 provider send            PASS (two observed)
D. corresponding message visibly received               PASS (two observed)
E. post-send grant behavior observed                     PASS / FINDING: SENT != proven EXHAUSTED
H. no secret material persisted in canonical evidence   PASS
```

## Gate items still open

```text
A. exact client wx.requestSubscribeMessage result        OPEN
F. exact duplicate/replay/provider-idempotency boundary  OPEN
G. non-zero raw errcode mappings                         OPEN / only map when evidenced
```

The deterministic Gate 0D-3 crash safety rule remains unchanged:

```text
IN_FLIGHT at crash/restart
  -> AMBIGUOUS
  -> no blind automatic resend
```

Two successful sends do not prove provider-side request idempotency or reconciliation. Exact duplicate/replay evidence is still required for item F.
