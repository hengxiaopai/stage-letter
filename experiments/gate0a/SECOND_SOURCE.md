# Gate 0A — Douyin OFFLINE Second-Source Spike

Status: **IN PROGRESS**

## Objective

Find a second Douyin source that can distinguish explicit `OFFLINE` from `UNKNOWN` for ordinary public creators who have not authorized Stage Letter.

Hard rule: absence of `room_id`, empty `data`, missing stream URLs, HTTP 200, parser success, stale room metadata, or request failure MUST NOT be interpreted as `OFFLINE` unless the source exposes an explicit state contract that is validated against independent ground truth.

## Current source roles

### TikHub — identity/profile + positive LIVE

Verified:

```text
creator search / identity resolution   PASS
exact Douyin ID -> UID                 PASS
UID LIVE detection                     PASS
LIVE room_id                           PASS
repeated LIVE polling                  PASS
known-OFFLINE explicit status          DEGRADED / INCONCLUSIVE
```

Known-OFFLINE `X.四五六` (`douyin_id=82553285031`, `uid=2206033664807300`) did not produce a decisive tested TikHub `live_status`. TikHub remains useful for identity/profile and LIVE metadata, but is not sufficient as the sole canonical state source.

### F2 — positive LIVE only

Research baseline: `Johnserf-Seed/f2` commit `7dab3e2ffffaa2535834d28fca99dbc2e89fa9d3`.

```text
F2 positive LIVE detection       PASS
F2 LIVE room_id                  PASS
F2 known-OFFLINE explicit 0      FAIL / NOT PROVIDED
F2 false-OFFLINE protection      PASS
F2 as OFFLINE confirmer          REJECTED
```

F2 remains an independent positive-LIVE control but does not solve OFFLINE confirmation.

## StreamGet — PROFILE/sec_uid status path

Repository: `ihmily/streamget`

Runtime baseline:

- StreamGet `4.0.10`
- Python `3.12.1`
- no Douyin login cookie
- local Gate probe: `streamget_status_probe.py`

Gate normalization:

```text
2 -> LIVE
4 -> OFFLINE
anything else / request failure / parse failure -> UNKNOWN
```

### Initial semantics controls

Known-OFFLINE `X.四五六` at `2026-08-17T13:39:26+08:00`:

```text
raw_room_status   = 4
anchor_name       = 𝑿.四五六🍉
normalized status = OFFLINE
```

Known-LIVE `央视网财经` at `2026-08-17T14:07:02+08:00`:

```text
raw_room_status   = 2
anchor_name       = 央视网财经
m3u8_present      = true
flv_present       = true
normalized status = LIVE
```

These established the explicit `4 -> OFFLINE` and `2 -> LIVE` semantics against independent ground truth.

Important metadata rule: OFFLINE responses can still carry previous room titles. Title or room-metadata presence is therefore not live-state evidence.

### Historical live-room URL repeat test — DEGRADED

Repeated probing of the old numeric room URL for `X.四五六` returned request/parse failures and therefore `UNKNOWN`, while the LIVE control remained `LIVE`.

Decision: historical `live.douyin.com/<room>` URLs are not reliable long-term PlatformAccount monitoring keys. Failures correctly remained `UNKNOWN`.

### Profile/sec_uid repeat test — PASS

Using identity-level profile URLs through StreamGet `fetch_app_stream_data()`:

```text
X.四五六 / independently OFFLINE
round 1 -> status=4 / OFFLINE / identity match
round 2 -> status=4 / OFFLINE / identity match
round 3 -> status=4 / OFFLINE / identity match

央视网财经 / independently LIVE
round 1 -> status=2 / LIVE / identity match
round 2 -> status=2 / LIVE / identity match
round 3 -> status=2 / LIVE / identity match
```

Formal `streamget_status_probe.py` replay also passed:

```text
2026-08-17T14:41:30+08:00  X.四五六    PROFILE -> 4 / OFFLINE
2026-08-17T14:41:46+08:00  央视网财经  PROFILE -> 2 / LIVE + m3u8/flv
```

Preferred experimental monitoring input is now stable `PlatformAccount` identity, especially `sec_uid` / profile URL. Live-room URLs remain metadata/navigation targets, not canonical identity keys.

## Failure-safety validation — PASS

The formal probe was deliberately exercised against invalid identity and forced network failure.

Invalid profile at `2026-08-17T14:47:34+08:00`:

```text
input_mode       = PROFILE
status           = UNKNOWN
raw_room_status  = null
error_type       = STREAMGET_REQUEST_OR_PARSE_ERROR
message          = RuntimeError
```

Forced proxy/network failure at `2026-08-17T14:48:32+08:00`:

```text
input_mode       = PROFILE
status           = UNKNOWN
raw_room_status  = null
error_type       = STREAMGET_REQUEST_OR_PARSE_ERROR
message          = RuntimeError
```

Decision:

```text
invalid identity -> UNKNOWN         PASS
forced network failure -> UNKNOWN   PASS
request/runtime failure -> UNKNOWN  PASS
UNKNOWN != OFFLINE                  PASS
false-OFFLINE protection            PASS
FAILURE_SAFETY                       PASS
```

## Initial multi-creator matrix — PASS 6/6

Four additional creators were manually checked in Douyin and probed through the same no-cookie PROFILE/sec_uid path at approximately `2026-08-17T14:53+08:00`.

| Creator | Independent ground truth | StreamGet | Raw status | Stream evidence | Result |
|---|---|---|---:|---|---|
| 🍒慢热💕 | OFFLINE | OFFLINE | 4 | none | PASS |
| 大马猴电竞 | LIVE | LIVE | 2 | m3u8 + flv | PASS |
| 花花果果⁵²⁹⁹ | LIVE | LIVE | 2 | m3u8 + flv | PASS |
| 陈泽- | OFFLINE | OFFLINE | 4 | none | PASS |

Together with the previously verified controls:

| Creator | Independent ground truth | StreamGet | Raw status | Result |
|---|---|---|---:|---|
| 𝑿.四五六🍉 | OFFLINE | OFFLINE | 4 | PASS |
| 央视网财经 | LIVE | LIVE | 2 | PASS |

Balanced initial matrix:

```text
LIVE creators      3 / 3 PASS
OFFLINE creators   3 / 3 PASS
total              6 / 6 PASS
identity matches   6 / 6 PASS
wrong states       0
```

This is sufficient to mark **initial multi-creator validation PASS** for Gate 0A.

### Additional metadata findings

The matrix reinforced two metadata constraints:

1. `🍒慢热💕` was manually OFFLINE and returned explicit status `4`, yet title was `笑笑 💕正在直播`. Therefore text such as `正在直播` inside `title` is stale/untrusted for canonical state.
2. OFFLINE samples returned `live_url` values such as `https://live.douyin.com/989851X` and `https://live.douyin.com/9896719.`. Therefore an OFFLINE `live_url` must be treated as provider metadata/navigation data, not proof of an active room and not a canonical identity key.

Canonical state remains the explicit successfully parsed status bound to the verified profile identity.

## Current StreamGet Gate decision

```text
explicit OFFLINE semantics                    PASS
explicit LIVE semantics                       PASS
PROFILE OFFLINE repeated stability            PASS (3/3)
PROFILE LIVE repeated stability               PASS (3/3)
formal PROFILE replay                         PASS
no-cookie ordinary-public path                PASS
identity consistency                          PASS
failure -> UNKNOWN                            PASS
false-OFFLINE protection                      PASS
initial multi-creator validation              PASS (6/6)
historical room-URL OFFLINE stability         DEGRADED / non-primary
PROFILE_STATUS_CONFIRMATION_CANDIDATE         PASS / PROMOTED
```

This is not production approval and does not make Gate 0A complete by itself.

## Lifecycle evidence — NEXT HARD GATE

The remaining core behavioral proof is a real same-creator lifecycle using one stable profile identity:

```text
OFFLINE (status=4)
    -> LIVE (status=2)
    -> OFFLINE (status=4)
```

`streamget_lifecycle_watch.py` captures this transition as timestamped JSONL while reusing `streamget_status_probe.py` as the single normalization authority. `UNKNOWN` observations are logged but never advance or close the lifecycle.

### Watcher Windows transport issue — FIXED

The first watcher run on `X.四五六` produced repeated:

```text
WATCHER_EMPTY_PROBE_OUTPUT
```

while the same profile succeeded when `streamget_status_probe.py` was invoked directly. This isolated the problem to the watcher's subprocess/stdout wrapper rather than StreamGet state semantics.

On Windows, redirected child-process stdout can use a different text encoding from the interactive Git Bash console. The probe output contains styled Unicode/emoji creator names, so the child could fail before JSON reached the parent. The watcher has therefore been changed to import and call the canonical async `probe()` function in-process instead of spawning a child and reparsing JSON stdout.

Safety remains unchanged:

```text
probe exception / invalid result -> UNKNOWN
UNKNOWN never advances lifecycle
```

The failed pre-fix JSONL remains diagnostic evidence only and must not count as lifecycle state evidence.

Recommended starting target is an independently confirmed currently-OFFLINE profile so the watcher can capture the complete sequence without reconstructing earlier state.

## Remaining Gate 0A work

1. Capture one real same-creator `OFFLINE -> LIVE -> OFFLINE` lifecycle with stable identity and timestamps.
2. Confirm metadata completeness required by Gate 0A: room identifier strategy, room/live URL, title, and source start time where actually available; missing fields must remain explicitly unavailable rather than invented.
3. Keep production authorization/compliance as a separate unresolved track. Technical feasibility does not equal platform authorization.
4. Only after lifecycle and required metadata evidence pass should Gate 0A be considered for completion and handoff to Gate 0B.

## Decision rules

- Only explicit, ground-truth-consistent state fields can advance a candidate.
- `status=2` and `status=4` are accepted only when identity is correct and the response is successfully parsed.
- Failures, missing state, risk control, schema drift, or unsupported values remain `UNKNOWN`.
- `UNKNOWN` never closes a session.
- Metadata presence does not override explicit state.
- Historical room URLs are not canonical identity keys.
- Never convert absence into OFFLINE.
