# Gate 0D-4 — Real WeChat Evidence — 2026-08-18

Status: **PASS / REAL ACCEPTANCE COMPLETE**

This sanitized record captures only non-secret facts from the real WeChat subscription-message experiment. Raw local JSON evidence remains under `experiments/gate0d/data/` and is gitignored.

## A. Real client subscription result — PASS

Observed from the real mini-program `wx.requestSubscribeMessage` callback:

```json
{
  "callback": "success",
  "errMsg": "requestSubscribeMessage:ok",
  "templateResult": "accept"
}
```

This is direct client evidence that the request completed through the success callback and the tested template result was `accept`.

## B/C/D. Real provider send + phone receipt — PASS

### Send #1

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

The intended WeChat account visibly received the corresponding notification at approximately 15:02 local time.

### Send #2

A second ordinary send used the same app/template/openid path without an intentionally repeated `wx.requestSubscribeMessage` call between send #1 and send #2.

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

The intended WeChat account visibly received the second notification at approximately 15:10 local time.

## E. Post-send grant behavior — PASS

The two real successful sends disproved the earlier deterministic assumption that one successful send proves global grant exhaustion.

Corrected semantic rule:

```text
SENT
  -> terminal success for this logical NotificationDelivery
  -> one send entitlement was used
  -> DO NOT infer global grant exhaustion without explicit provider evidence

explicit grant-invalid/exhaustion evidence
  -> may mark local grant state EXHAUSTED
```

The corrected deterministic Gate 0D suite was rerun successfully: **54/54 PASS**.

## F. Exact replay / provider idempotency boundary — PASS

A dedicated controlled replay experiment used:

```text
same process
same access token
same openid
same template id
same template data
same page/miniprogram_state/lang
same request-body fingerprint
```

Observed replay evidence:

```text
experiment                    EXACT_PAYLOAD_REPLAY
replay_count                  2
same_access_token_for_both    true
openid_fingerprint            cbdafe5eb1a0ea94
request_payload_fingerprint   9e040003c7649066

action #1
  errcode                     0
  errmsg                      ok
  normalized                  SENT
  msgid                       4654832376731369477

action #2
  errcode                     0
  errmsg                      ok
  normalized                  SENT
  msgid                       4654832384247562248
```

The provider returned two distinct `msgid` values, and the intended phone/account visibly received **two corresponding identical notifications**.

Therefore, under the tested conditions, exact same-payload replay was accepted as two independent sends; no automatic provider deduplication was observed.

This is sufficient to freeze the production safety rule:

```text
IN_FLIGHT at process crash
  -> AMBIGUOUS
  -> no blind automatic resend
```

Stage Letter must not claim provider-backed exactly-once delivery for this operation. Logical delivery idempotency remains a Stage Letter responsibility; an unresolved external side effect cannot be safely retried without reconciliation evidence.

## G. Non-zero raw provider mapping discipline — PASS

The real probe intentionally maps only:

```text
errcode == 0                -> SENT
transport failure           -> NETWORK_ERROR
other non-zero provider     -> UNMAPPED_PROVIDER_ERROR
```

A real pre-send credential failure was also observed earlier at `code2session` (`errcode=40125`, provider message reporting an invalid AppSecret). It was correctly kept outside user grant / notification-delivery outcomes and was not misclassified as `USER_REJECTED`, `GRANT_INVALID`, `RATE_LIMITED`, or similar.

Gate acceptance does not require manufacturing arbitrary provider failures. The frozen rule is that a non-zero raw WeChat code may enter a more specific Stage Letter outcome only when current provider documentation and/or direct observed evidence supports that exact mapping. Unknown codes remain conservative/unmapped.

## H. Secret handling — PASS

Canonical evidence persists no AppSecret, access token, session key, fresh login code, or raw openid. Raw local evidence is gitignored. Only fingerprints and sanitized provider facts are promoted here.

## Final Gate 0D-4 decision

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

### Permanent limitation captured by the Gate

The experiment does **not** prove that WeChat exposes no reconciliation facility anywhere in its platform. It proves the narrower production-relevant fact required by Stage Letter: sending the exact same subscription-message payload twice in the tested path produced two accepted provider responses, two distinct message IDs, and two phone receipts. Therefore Stage Letter cannot rely on payload equality for provider deduplication and must preserve `AMBIGUOUS` after crash-before-response.