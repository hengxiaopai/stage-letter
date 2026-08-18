# Gate 0D-4 — Real WeChat Acceptance Evidence

Status: **READY / MANUAL REAL-PROVIDER EVIDENCE REQUIRED**

## Purpose

Gate 0D-4 is the only Gate 0D stage allowed to claim real WeChat provider behavior.
The deterministic models from 0D-1/0D-2/0D-3 are not sufficient evidence for:

- real client subscription grant results;
- real provider `errcode` / `errmsg` mapping;
- real one-time grant consumption;
- real message receipt on a phone;
- provider-side idempotency or reconciliation capability.

Until this stage is captured, Gate 0D remains **IN PROGRESS**.

## Safety rules

```text
never commit AppSecret
never commit access_token
never commit session_key
never commit a fresh wx.login code
never print/persist access_token or session_key
non-zero provider errcode is not guessed into a domain outcome
```

The probe stores only fingerprints for AppID, template ID and openid, plus raw
provider `errcode` / `errmsg` diagnostics.

## Components

```text
experiments/gate0d/wechat-real-demo/
    minimal client probe for wx.requestSubscribeMessage + wx.login

experiments/gate0d/real_wechat_probe.py
    real service-side code2session / access-token / subscribe-message send probe
```

The mini-program demo contains no AppID. Import it in WeChat DevTools with the
actual Stage Letter mini-program AppID for the manual experiment.

## Required operator-owned values

```text
AppID
AppSecret                  (enter locally only; never paste into chat/Git)
real subscription template ID
fresh wx.login code OR known openid
template data JSON matching the selected template fields
```

`AppSecret` should be entered through the probe prompt or a local process
environment variable. Do not write it into repository files.

## Phase A — Real client grant truth

1. Import `experiments/gate0d/wechat-real-demo` into WeChat DevTools using the
   real mini-program AppID.
2. Preview/open it on a real phone when possible.
3. Paste the real subscription template ID into the page.
4. Tap **请求一次订阅授权** from the user gesture.
5. Capture the returned `templateResult` and `errMsg`.
6. Tap **获取新的 wx.login code** only immediately before the service-side run
   if an openid is not already available.

Record the exact client result; do not infer `GRANTED` from a UI impression.

## Phase B — Prepare template data

Create a local JSON file whose keys exactly match the selected real template.
Example shape only:

```json
{
  "thing1": {"value": "主播已开播"},
  "time2": {"value": "2026-08-18 14:30"}
}
```

The key names above are placeholders. Replace them with the actual template
fields from the WeChat platform before sending.

Keep this data file local if it contains user/private information.

## Phase C — Dry validation

From repository root:

```bash
./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0d/real_wechat_probe.py \
  --appid "YOUR_APP_ID" \
  --template-id "YOUR_TEMPLATE_ID" \
  --data-file "/path/to/template-data.json"
```

Expected: input/evidence shape is printed, but no provider send occurs.

## Phase D — Real send

Preferred when a known openid is available:

```bash
WECHAT_OPENID="..." \
./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0d/real_wechat_probe.py \
  --appid "YOUR_APP_ID" \
  --template-id "YOUR_TEMPLATE_ID" \
  --data-file "/path/to/template-data.json" \
  --miniprogram-state developer \
  --send
```

If openid is not already available, use a fresh `wx.login` code from Phase A:

```bash
./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0d/real_wechat_probe.py \
  --appid "YOUR_APP_ID" \
  --template-id "YOUR_TEMPLATE_ID" \
  --login-code "FRESH_WX_LOGIN_CODE" \
  --data-file "/path/to/template-data.json" \
  --miniprogram-state developer \
  --send
```

The script prompts for AppSecret without echoing it when `WECHAT_APP_SECRET` is
not already set.

## Conservative provider mapping

The real probe intentionally maps only:

```text
errcode == 0                -> SENT
transport failure           -> NETWORK_ERROR
any other provider response -> UNMAPPED_PROVIDER_ERROR
```

A non-zero WeChat `errcode` is not promoted to USER_REJECTED, GRANT_INVALID,
AUTH_REQUIRED, TEMPLATE_INVALID or RATE_LIMITED until current provider evidence
and documentation support that exact classification.

## Required PASS evidence

Gate 0D-4 needs all of the following before Gate 0D can close:

```text
A. client subscription result captured from real mini-program/phone
B. real send provider response captured
C. at least one real errcode=0 provider send
D. corresponding message visibly received by the intended WeChat account
E. one-time grant behavior observed after successful send
F. duplicate/replay boundary documented from real provider behavior
G. raw non-zero errors used by Stage Letter mapped only with evidence
H. no secret material persisted in repository evidence
```

### Exactly-once limitation

If the provider exposes no reliable request-idempotency or send reconciliation
facility for this operation, the Gate 0D-3 crash boundary remains:

```text
IN_FLIGHT at process crash
    -> AMBIGUOUS
    -> no blind automatic resend
```

Do not weaken this rule based only on a successful happy-path send.

## Evidence handling

The probe writes normalized evidence under:

```text
experiments/gate0d/data/wechat-real-*.json
```

That directory is local evidence and should not be committed raw. After review,
copy only sanitized facts required for the Gate decision into this document or
a dedicated sanitized evidence record.
