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

- known OFFLINE creator (`X.四五六`, Douyin ID `82553285031`) returns no decisive `live_status` via the tested UID and sec_uid live routes.
- User Search V2 production response did not contain the documented `live_status` field.

Conclusion: TikHub remains useful as a LIVE detector and identity/profile source, but is not yet sufficient as the sole canonical state source.

## Candidate ranking

### 1. F2 direct Douyin web status — PRIMARY SPIKE

Repository: `Johnserf-Seed/f2`

Research baseline commit: `7dab3e2ffffaa2535834d28fca99dbc2e89fa9d3`

Relevant implementation:

- endpoint: `https://live.douyin.com/webcast/distribution/check_user_live_status/`
- request model: `UserLiveStatus(user_ids=...)`
- response filter path: `$.data[0].user_live[0].live_status`
- F2 source comment: `1开播 0未开播`
- room id path: `$.data[0].user_live[0].room_id`

Why first:

- self-hosted/open-source path instead of another opaque paid aggregator;
- exposes an explicit binary live-state field in the parser contract;
- works from stable numeric UID, matching Stage Letter's frozen `PlatformAccount` design;
- lets Gate 0A preserve `UNKNOWN != OFFLINE` by accepting only explicit `0` or `1`.

Probe: `f2_live_status_probe.py`

Gate acceptance for F2 requires all of the following:

1. X.四五六 is independently confirmed OFFLINE in Douyin App/web;
2. the F2/direct endpoint returns `live_status=0` for UID `2206033664807300`;
3. a currently LIVE control returns `live_status=1` plus a non-empty room id;
4. failures, captcha, 403/429, missing arrays, or schema drift normalize to UNKNOWN;
5. the result is reproducible across repeated runs and at least several creators.

### 2. DouyinLiveJava `/status` service — SECONDARY

The project documents a status contract by `uid`/`secUid` returning `live=true|false` and `roomId`, but the status service is mediated by its signing/service layer (self-hosted or RapidAPI). This makes it less independent than the F2 direct-web path, so it is not the first test.

### 3. StreamGet — TERTIARY

StreamGet exposes `is_live` and supports Douyin without a login cookie in its documented support matrix. It is useful as an additional control, but its principal purpose is stream extraction from live-room URLs rather than authoritative user-level OFFLINE state.

### 4. Official Douyin Live SDK / webcast-open — PRODUCTION TRACK, NOT GATE SUBSTITUTE

Official Douyin documentation exposes room information and `webcast.room.status_change` callbacks, including start/stop events. However, the documented anchor scope is limited to creators admitted through creator authorization or an operations whitelist. That does not satisfy Gate 0A's ordinary-public, non-authorized creator requirement.

It should remain the preferred long-term compliance/production track where cooperation/authorization is available, but cannot replace the current public-creator feasibility test.

## Next execution

Run F2 first **without a login cookie** against:

- OFFLINE target: X.四五六 — UID `2206033664807300`
- LIVE control: 旭旭宝宝 — UID `74810581616` (only while independently verified live)

Expected decisive evidence:

```text
X.四五六  -> raw_live_status = 0 -> OFFLINE
旭旭宝宝 -> raw_live_status = 1 -> LIVE + room_id
```

If the no-cookie request is blocked, a cookie-backed run may be used only as a diagnostic. It does not by itself satisfy the ordinary-public unauthenticated Gate requirement.

## Decision rule

- If F2 returns explicit and correct 0/1 across OFFLINE/LIVE controls: promote it to `OFFLINE_CONFIRMATION_CANDIDATE` and begin repeated/multi-sample validation.
- If it is blocked or ambiguous without login: keep TikHub LIVE detection, mark F2 DEGRADED for Gate 0A, and move to the next independent candidate.
- Never convert absence into OFFLINE.
