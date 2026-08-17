# Gate 0A — Douyin OFFLINE Second-Source Spike

Status: **IN PROGRESS**

## Objective

Find a second Douyin source that can distinguish explicit `OFFLINE` from `UNKNOWN` for ordinary public creators who have not authorized Stage Letter.

Hard rule: absence of `room_id`, empty `data`, missing stream URLs, HTTP 200, parser success, or stale room metadata MUST NOT be interpreted as `OFFLINE` unless the source exposes an explicit state contract that is validated against known ground truth.

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

Known-OFFLINE X.四五六 returned no explicit `0` and therefore normalized to `UNKNOWN`.
Known-LIVE 央视网财经 returned explicit `1` plus room id and normalized to `LIVE`.

Decision:

```text
F2 positive LIVE detection       PASS
F2 LIVE room_id                  PASS
F2 known-OFFLINE explicit 0      FAIL / NOT PROVIDED
F2 false-OFFLINE protection      PASS
F2 as OFFLINE confirmer          REJECTED
```

F2 may remain useful as an independent positive-LIVE control, but it does not solve the OFFLINE-confirmation blocker.

### 2. StreamGet — PROFILE/SEC_UID STATUS PATH PROMOTED

Repository: `ihmily/streamget`

Runtime baseline:

- StreamGet version `4.0.10`
- Python `3.12.1`
- no Douyin login cookie
- local Gate probe: `streamget_status_probe.py`

The Gate normalizes only explicit room status values:

```text
2 -> LIVE
4 -> OFFLINE
anything else / request failure / parse failure -> UNKNOWN
```

#### Initial single controls

Known-OFFLINE X.四五六, historical live-room URL `https://live.douyin.com/975645387460`:

```text
2026-08-17T13:39:26+08:00
raw_room_status   = 4
anchor_name       = 𝑿.四五六🍉
title             = 重生之我在旭旭宝宝传媒当歌手
normalized status = OFFLINE
```

Known-LIVE 央视网财经:

```text
2026-08-17T14:07:02+08:00
raw_room_status   = 2
anchor_name       = 央视网财经
title             = 央视财经频道节目直播
m3u8_present      = true
flv_present       = true
normalized status = LIVE
```

These established the explicit `4 -> OFFLINE` and `2 -> LIVE` semantics against independent ground truth.

Important metadata note: the OFFLINE response still carried the previous room title, proving title/room metadata presence is not live-state evidence.

#### Historical room-URL repeat test — DEGRADED FOR OFFLINE

Three repeated dual-control rounds were run using:

- OFFLINE: `https://live.douyin.com/975645387460`
- LIVE: `https://live.douyin.com/nuanxinnengl`

Results:

```text
X.四五六 historical room URL:
round 1 -> UNKNOWN / request-or-parse error
round 2 -> UNKNOWN / request-or-parse error
round 3 -> UNKNOWN / request-or-parse error

央视网财经 live URL:
round 1 -> LIVE / status=2 / stream URLs present
round 2 -> LIVE / status=2 / stream URLs present
round 3 -> LIVE / status=2 / stream URLs present
```

Decision: a historical numeric live-room URL is not reliable enough as the preferred long-term PlatformAccount monitoring key for an OFFLINE creator. Failures correctly remained `UNKNOWN`, so false-OFFLINE protection still PASSed.

#### Profile/sec_uid repeat test — PASS

To compare equivalent identity-level paths, StreamGet `fetch_app_stream_data()` was run three times for both creators using profile/sec_uid URLs.

OFFLINE X.四五六:

```text
profile sec_uid = MS4wLjABAAAADlel7zsI5JBe2Uv_FZoX_Ecv8iiK38CXB-3ah_9SJE14892-nxueFDQU71B4FRsz
round 1 -> status=4 / OFFLINE / anchor=𝑿.四五六🍉
round 2 -> status=4 / OFFLINE / anchor=𝑿.四五六🍉
round 3 -> status=4 / OFFLINE / anchor=𝑿.四五六🍉
live_url returned = https://live.douyin.com/82553285031
```

LIVE 央视网财经:

```text
profile sec_uid = MS4wLjABAAAAzrRqzBM_qqg3Q9h-IxA1MQSimf8ZgoLlw7f1r2NIvvo
round 1 -> status=2 / LIVE / anchor=央视网财经
round 2 -> status=2 / LIVE / anchor=央视网财经
round 3 -> status=2 / LIVE / anchor=央视网财经
live_url returned = https://live.douyin.com/nuanxinnengl
```

This is the strongest current StreamGet Gate evidence because both LIVE and OFFLINE use the same identity-level input mode and both remained stable across all three rounds.

#### Formal Gate probe replay — PASS

After `streamget_status_probe.py` was upgraded to support PROFILE inputs directly, the formal probe was replayed against both controls without a Douyin login cookie.

OFFLINE X.四五六 at `2026-08-17T14:41:30+08:00`:

```text
input_mode       = PROFILE
raw_room_status  = 4
status           = OFFLINE
anchor_name      = 𝑿.四五六🍉
live_url         = https://live.douyin.com/82553285031
m3u8_present     = false
flv_present      = false
confidence       = 0.90
```

LIVE 央视网财经 at `2026-08-17T14:41:46+08:00`:

```text
input_mode       = PROFILE
raw_room_status  = 2
status           = LIVE
anchor_name      = 央视网财经
live_url         = https://live.douyin.com/nuanxinnengl
m3u8_present     = true
flv_present      = true
confidence       = 0.95
```

The formal probe therefore matches the earlier manual 3x dual-control experiment and confirms that the implemented PROFILE path preserves the expected semantics.

Current decision:

```text
StreamGet explicit OFFLINE semantics          PASS
StreamGet explicit LIVE semantics             PASS
StreamGet profile OFFLINE repeated stability  PASS (3/3)
StreamGet profile LIVE repeated stability     PASS (3/3)
Formal PROFILE probe OFFLINE replay            PASS
Formal PROFILE probe LIVE replay               PASS
StreamGet identity consistency                PASS
StreamGet no-cookie path                      PASS
Historical room-URL OFFLINE stability         DEGRADED
False-OFFLINE protection                      PASS
PROFILE_STATUS_CONFIRMATION_CANDIDATE         PASS / PROMOTED
```

Preferred experimental monitoring input is now stable `PlatformAccount` identity, especially `sec_uid`/profile URL, not a historical room URL. Room/live URLs remain metadata and navigation targets, not canonical identity keys.

`streamget_status_probe.py` now supports both PROFILE and LIVE_URL inputs and marks PROFILE as the preferred Gate monitoring path.

The Gate 0A Douyin Smoke for commit `05fb257e9a92074c81e5ada8d6dd1fb338fadf94` completed successfully (run `32002387708`).

This is still not production approval and does not make Gate 0A complete by itself.

### 3. DouyinLiveJava `/status` service — DEFERRED / MEDIATED

The documented `/status?uid=` / `/status?secUid=` contract is attractive, but the convenient hosted path is mediated by a RapidAPI gateway under the TikHub team account and therefore is not sufficiently independent from the current TikHub primary source. Keep it as a diagnostic/alternative unless an independent self-hosted status implementation is available.

### 4. Official Douyin Live SDK / webcast-open — PRODUCTION TRACK, NOT GATE SUBSTITUTE

Official platform APIs remain the preferred compliance/production track where creator authorization or operations whitelist access is available, but that scope does not replace Gate 0A's ordinary-public unauthenticated feasibility test.

## Next execution

Do not add another data-source candidate yet. Continue with StreamGet PROFILE input as the current status-confirmation candidate:

1. Add several independently verified LIVE and OFFLINE creators and run the same profile/sec_uid path.
2. Verify request/risk-control/schema failures normalize to `UNKNOWN`, never `OFFLINE`.
3. Capture a real same-creator `OFFLINE -> LIVE -> OFFLINE` lifecycle with stable identity and timestamps.
4. Record title, live URL, stream presence, room id and source start time as metadata separate from canonical state.
5. Only after multi-creator validation and lifecycle evidence pass should Gate 0A be considered for completion and handoff to Gate 0B.

## Decision rule

- Only explicit, ground-truth-consistent state fields can advance a candidate.
- `status=2` and `status=4` are accepted only when identity is correct and the response is successfully parsed.
- Failures, missing state, risk control, schema drift, or unsupported values remain `UNKNOWN`.
- Metadata presence does not override explicit state.
- Historical room URLs are not canonical identity keys.
- Never convert absence into OFFLINE.
