# Gate 0D-4 — Real WeChat Evidence — 2026-08-18

Status: **PARTIAL PASS / REAL HAPPY PATH CONFIRMED**

This sanitized record captures only non-secret facts from the real WeChat subscription-message experiment. Raw local JSON evidence remains under `experiments/gate0d/data/` and is gitignored.

## Real provider send

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

The real probe therefore crossed all of these boundaries successfully:

```text
wx.login code
  -> code2session
  -> openid obtained
  -> access token obtained
  -> subscribe-message provider call
  -> errcode = 0 / errmsg = ok
```

## Visual receipt evidence

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

This confirms that the real provider success was not only an API `errcode=0`; the message was actually rendered to the receiving WeChat account.

## Gate items confirmed

```text
B. real send provider response captured             PASS
C. at least one real errcode=0 provider send        PASS
D. corresponding message visibly received           PASS
H. no secret material persisted in canonical evidence PASS
```

## Gate items still open

```text
A. exact client wx.requestSubscribeMessage result   OPEN
E. one-time grant behavior after successful send    OPEN
F. duplicate/replay/provider-idempotency boundary   OPEN
G. non-zero raw errcode mappings                    OPEN / only map when evidenced
```

The deterministic Gate 0D-3 safety rule remains unchanged:

```text
IN_FLIGHT at crash/restart
  -> AMBIGUOUS
  -> no blind automatic resend
```

A successful happy-path send does not prove provider-side exactly-once semantics.
