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

### 2. DouyinLiveJava `/status` service — NEXT SPIKE

Repository: `lulajax/DouyinLiveJava`

The project documents a status contract by `uid`/`secUid`:

```text
GET /status?uid=<numeric uid>
GET /status?secUid=<sec_uid>
  -> { uid, secUid, nickname, live: true|false, roomId }
```

The documented contract explicitly says `live=false` has `roomId=null`, which makes it worth testing against the same known-OFFLINE and known-LIVE controls.

Caveat: the status service is mediated by a signing/service layer (self-hosted or RapidAPI). This is less independent than F2's direct-web path, so Gate evidence must record the actual provider and must not assume `live=false` is trustworthy until it matches independent ground truth.

Acceptance requires:

1. X.四五六 independently confirmed OFFLINE -> explicit `live=false`, `roomId=null`;
2. a currently LIVE control -> explicit `live=true`, non-empty `roomId`;
3. failures, quota errors, auth/sign failures, missing fields, or schema drift -> `UNKNOWN`, never OFFLINE;
4. repeat across several creators before promotion.

### 3. StreamGet — TERTIARY

Repository: `ihmily/streamget`

StreamGet exposes `StreamData.is_live` and supports Douyin without a login cookie in its documented support matrix. It requires Node.js for Douyin and is principally a stream extractor from live-room URLs, so it remains a tertiary control rather than the preferred user-level OFFLINE source.

### 4. Official Douyin Live SDK / webcast-open — PRODUCTION TRACK, NOT GATE SUBSTITUTE

Official Douyin documentation exposes room information and `webcast.room.status_change` callbacks, including start/stop events. However, the documented anchor scope is limited to creators admitted through creator authorization or an operations whitelist. That does not satisfy Gate 0A's ordinary-public, non-authorized creator requirement.

It should remain the preferred long-term compliance/production track where cooperation/authorization is available, but cannot replace the current public-creator feasibility test.

## Next execution

Move to DouyinLiveJava `/status` as the next second-source spike. Use the same controls whenever their independent ground truth is current:

- OFFLINE: X.四五六 — UID `2206033664807300`
- LIVE: 央视网财经 — UID `720916559455351` (only while independently verified live)

Do not spend additional effort trying to reinterpret F2's null OFFLINE response.

## Decision rule

- Only explicit, ground-truth-consistent state fields can advance a candidate.
- A candidate that proves LIVE but expresses OFFLINE only as absence/null is rejected for the OFFLINE confirmer role.
- Never convert absence into OFFLINE.
