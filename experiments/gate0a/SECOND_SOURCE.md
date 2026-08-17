# Gate 0A — Douyin OFFLINE Second-Source Spike

Status: **IN PROGRESS**

## Objective

Find a second Douyin source that can distinguish explicit `OFFLINE` from `UNKNOWN` for ordinary public creators who have not authorized Stage Letter.

Hard rule: absence of `room_id`, empty `data`, missing stream URLs, HTTP 200, or parser success MUST NOT be interpreted as `OFFLINE` unless the source exposes an explicit state contract that is validated against known ground truth.

## Current primary source: TikHub

Verified strengths:

- creator search / identity resolution: PASS
- exact Douyin ID -> UID: PASS
- UID LIVE detection: PASS
- LIVE room_id: PASS
- repeated LIVE polling: PASS

Verified weakness:

- known OFFLINE creator (`X.四五六`, Douyin ID `82553285031`, UID `2206033664807300`) returns no decisive `live_status` via the tested UID and sec_uid live routes.
- User Search V2 production response did not contain the documented `live_status` field.

Conclusion: TikHub remains useful as a LIVE detector and identity/profile source, but is not sufficient as the sole canonical state source.

## Candidate results

### 1. F2 direct Douyin web status — REJECTED FOR OFFLINE CONFIRMATION

Repository: `Johnserf-Seed/f2`

Research baseline commit: `7dab3e2ffffaa2535834d28fca99dbc2e89fa9d3`

Relevant implementation:

- endpoint: `https://live.douyin.com/webcast/distribution/check_user_live_status/`
- request model: `UserLiveStatus(user_ids=...)`
- response filter path: `$.data[0].user_live[0].live_status`
- F2 source contract: `1 -> live`, `0 -> not live`
- room id path: `$.data[0].user_live[0].room_id`

Probe: `f2_live_status_probe.py`

Runtime note:

- isolated Gate virtualenv used Python 3.12.1;
- F2 installed as version `0.0.1.7`;
- local SOCKS proxy environment required installing `httpx[socks]==0.28.1` / `socksio` before the Douyin model and crawler imports succeeded;
- this was an environment dependency issue, not a state-semantics result.

#### Known-OFFLINE control — X.四五六

Independent ground truth: OFFLINE in Douyin App/web.

Input:

- Douyin ID: `82553285031`
- UID: `2206033664807300`
- cookie: none

Observed at `2026-08-17T10:59:09+08:00`:

```text
api_status_code   = 0
returned_user_id  = null
raw_live_status   = null
room_id           = null
normalized status = UNKNOWN
error_type        = NO_DECISIVE_LIVE_STATUS
```

Result: **INCONCLUSIVE**. The direct endpoint did not expose an explicit `0`, therefore this sample MUST remain `UNKNOWN` and cannot be promoted to OFFLINE.

#### Known-LIVE control — 央视网财经

Independent ground truth: profile visibly showed `直播中` during the test window.

Identity resolved through TikHub Creator Search with strong identity match:

- nickname: `央视网财经`
- Douyin ID: `nuanxinnengl`
- UID: `720916559455351`
- match reason: `EXACT_DOUYIN_ID`

F2 no-cookie result observed at `2026-08-17T13:17:28+08:00`:

```text
api_status_code   = 0
returned_user_id  = 720916559455351
raw_live_status   = 1
room_id           = 7664459902303111978
normalized status = LIVE
confidence        = 0.95
```

Evidence:

- `explicit_user_live_status:1`
- `room_id_present`

Result: **PASS for positive LIVE detection**.

#### F2 decision

The same no-cookie path can positively prove a LIVE creator but did not provide an explicit `0` for a known-OFFLINE creator.

Therefore:

```text
F2 runtime / request path        PASS
F2 positive LIVE detection       PASS
F2 LIVE room_id                  PASS
F2 known-OFFLINE explicit 0      FAIL / NOT PROVIDED
F2 false-OFFLINE protection      PASS
F2 as OFFLINE confirmer          REJECTED
```

F2 may remain useful as an independent positive-LIVE control, but it does not solve Gate 0A's OFFLINE-confirmation blocker. Do not infer OFFLINE from null/missing `user_live` data.

### 2. StreamGet — OFFLINE SINGLE-SAMPLE PASS / LIVE CONTROL PENDING

Repository: `ihmily/streamget`

Runtime baseline:

- StreamGet version `4.0.10`
- Python `3.12.1`
- no Douyin login cookie
- local Gate probe: `streamget_status_probe.py`

The Gate probe normalizes only explicit room status values already used by StreamGet's Douyin implementation:

```text
2 -> LIVE
4 -> OFFLINE
anything else / parse failure -> UNKNOWN
```

#### Known-OFFLINE control — X.四五六

Independent ground truth: OFFLINE in Douyin App/web.

Input:

- room URL: `https://live.douyin.com/975645387460`
- cookie: none

Observed at `2026-08-17T13:39:26+08:00`:

```text
raw_room_status   = 4
anchor_name       = 𝑿.四五六🍉
title             = 重生之我在旭旭宝宝传媒当歌手
m3u8_present      = false
flv_present       = false
normalized status = OFFLINE
confidence        = 0.90
```

Evidence:

- `explicit_room_status:4`
- returned anchor identity matched the known target

Result: **PASS for one explicit OFFLINE control sample**.

This is the first tested independent local source in Gate 0A that has produced an explicit non-null state consistent with the independently observed OFFLINE ground truth. It is not yet sufficient for promotion to canonical OFFLINE confirmation because the same path still needs a known-LIVE control and repeated/multi-creator validation.

Current StreamGet status:

```text
StreamGet runtime / request path       PASS
Known-OFFLINE explicit status=4        PASS (1 sample)
Known-LIVE explicit status=2           NOT YET
False-OFFLINE protection               PASS by probe contract
OFFLINE_CONFIRMATION_CANDIDATE          PROVISIONAL / PENDING LIVE CONTROL
```

### 3. DouyinLiveJava `/status` service — DEFERRED / MEDIATED

Repository: `lulajax/DouyinLiveJava`

The project documents a status contract by `uid`/`secUid`:

```text
GET /status?uid=<numeric uid>
GET /status?secUid=<sec_uid>
  -> { uid, secUid, nickname, live: true|false, roomId }
```

The contract is attractive because it explicitly distinguishes `live=true|false`. However, the repository states that the client does not include the platform signing implementation and that the convenient hosted path is a RapidAPI gateway operated under the TikHub team account. A self-hosted signing/status service is possible only if the user supplies that implementation separately.

Therefore the hosted path is not sufficiently independent from the current TikHub primary source to be the next second-source Gate. Keep it as a diagnostic/alternative only, unless an independently self-hosted signer becomes available.

### 4. Official Douyin Live SDK / webcast-open — PRODUCTION TRACK, NOT GATE SUBSTITUTE

Official Douyin documentation exposes room information and `webcast.room.status_change` callbacks, including start/stop events. However, the documented anchor scope is limited to creators admitted through creator authorization or an operations whitelist. That does not satisfy Gate 0A's ordinary-public, non-authorized creator requirement.

It should remain the preferred long-term compliance/production track where cooperation/authorization is available, but cannot replace the current public-creator feasibility test.

## Next execution

Run a known-LIVE StreamGet control immediately while independent ground truth is still current. Preferred control: `央视网财经` if still visibly live.

The current Gate probe accepts `live.douyin.com/<web_rid>` URLs. If only a profile/sec_uid URL is available, first resolve a verified current live-room URL or extend the experimental probe to use StreamGet's app/profile URL path without weakening the explicit-state rule.

Only after StreamGet returns explicit `status=2` for a known-LIVE control should it be promoted to `OFFLINE_CONFIRMATION_CANDIDATE` and moved into repeated/multi-creator validation.

## Decision rule

- Only explicit, ground-truth-consistent state fields can advance a candidate.
- One correct OFFLINE sample is necessary but not sufficient; the same source must also correctly identify a known-LIVE sample.
- Failures, missing state, risk control, or schema drift remain UNKNOWN.
- Never convert absence into OFFLINE.
