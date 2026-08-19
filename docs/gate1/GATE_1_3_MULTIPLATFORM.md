# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A BILIBILI CORE+HTTP GATEWAY LANDED / UID-SCHEMA FIX LANDED / LOCAL+PROVIDER EVIDENCE PENDING**

Entry authority: Gate 1.3-3 PASS / CLOSED.

## 1. Slice plan

Gate 1.3-4 is split internally so each platform preserves only evidence it has
actually established:

```text
Gate 1.3-4A  Bilibili formal adapter + provider evidence
Gate 1.3-4B  Huya formal adapter + missing OFFLINE evidence resolution
Gate 1.3-4C  Douyu formal adapter + provider evidence
Gate 1.3-4D  cross-platform regression / registry acceptance
```

No platform is allowed to inherit another platform's state mapping.

## 2. Bilibili evidence authority

The accepted Gate 0B record establishes:

```text
stable external identity: Bilibili uid / space profile
live_status = 0 -> OFFLINE
live_status = 1 -> LIVE
live_status = 2 -> LIVE / carousel
other / missing / failure -> not decisive canonical truth
```

The recorded soak matrix included both decisive paths, with 139 ONLINE and 91
OFFLINE observations. It still lacked a real same-creator transition, so this
migration does not claim lifecycle proof.

Room id is live-room/navigation metadata; uid remains the formal PlatformAccount
identity.

## 3. Bilibili formal core

Landed:

```text
stage_letter/infrastructure/platforms/bilibili.py
tests/gate1/test_bilibili_formal_adapter.py
```

The adapter implements `LivePlatformAdapter` via an injected
`BilibiliProviderGateway`:

```text
resolve_identity(input) -> BilibiliIdentityRecord
fetch_profile(uid)      -> BilibiliProfileRecord
fetch_live(uid)         -> BilibiliLiveRecord
```

Canonical mapping is strict by type:

```text
integer 0 -> OFFLINE
integer 1 -> LIVE
integer 2 -> LIVE
bool / string lookalikes / other values -> UNKNOWN
```

Provider failure, timeout, rate limiting, schema drift, and identity mismatch
remain UNKNOWN for live reads.

## 4. Bilibili formal HTTP transport

Landed:

```text
stage_letter/infrastructure/platforms/bilibili_http.py
scripts/gate13_bilibili_provider_probe.py
tests/gate1/test_bilibili_http_gateway.py
```

Provider endpoints:

```text
uid path:
  /room/v1/Room/getRoomInfoOld?mid=<uid>

room path:
  /room/v1/Room/room_init?id=<room_id>
```

Formal resolution rules:

```text
space URL / numeric uid -> uid endpoint
live-room URL            -> room_init -> stable uid
canonical_url            -> https://space.bilibili.com/<uid>
```

The transport returns provider records only. Non-2xx, timeout, network,
non-JSON, provider nonzero code, missing data, or explicit uid mismatch become
normalized provider failures; none becomes OFFLINE merely because a request
failed.

## 5. First provider-run finding — getRoomInfoOld schema correction

The first operator LIVE/OFFLINE probes both stopped with:

```text
status = UNKNOWN
provider_failure_kind = SCHEMA_DRIFT
provider_source = bilibili.resolve
provider_failure_detail = invalid uid
```

This was not LIVE/OFFLINE evidence and not an input-URL defect. Inspection showed
the formal gateway had incorrectly required `getRoomInfoOld` to echo `uid` in
its `data` object. That endpoint is already keyed by the requested `mid` and may
omit uid. Its current status shape also uses `liveStatus` / `roundStatus`, while
historical Stage Letter fixtures used `live_status`.

The fix preserves identity safety without inventing provider truth:

```text
uid request + response omits uid
  -> requested positive uid remains stable identity

response explicitly includes uid
  -> it must match requested uid, otherwise AMBIGUOUS

getRoomInfoOld liveStatus
  0 -> raw 0
  1 -> raw 1

roundStatus = 1
  -> raw 2 / carousel

historical explicit live_status fixture
  -> remains supported for regression compatibility
```

The formal adapter above the gateway still owns canonical normalization:

```text
raw integer 0 -> OFFLINE
raw integer 1 -> LIVE
raw integer 2 -> LIVE
anything unsupported / failure -> UNKNOWN
```

No provider failure is converted to OFFLINE by this correction.

## 6. Huya evidence boundary before migration

The existing evidence record proves repeated LIVE observations with
`eLiveStatus=2`, but explicitly records that real OFFLINE ground truth had not yet
been established in the Gate 0B sample.

Therefore Gate 1.3-4B must not blindly promote the legacy table's `0 -> OFFLINE`
rule to formal canonical truth until a decisive current OFFLINE sample is verified:

```text
proven eLiveStatus=2 -> LIVE
failure / missing / unsupported -> UNKNOWN
0 -> OFFLINE requires provider-backed ground-truth confirmation in 1.3-4B
```

## 7. Douyu evidence boundary before migration

The existing evidence record establishes:

```text
show_status = 1 -> LIVE
show_status = 2 -> OFFLINE
```

It records `0 / 3 / 4` as ambiguous without additional evidence and warns that
list/recommendation absence must not be treated as OFFLINE. Gate 1.3-4C will
preserve that conservative boundary.

## 8. Gate 1.3-4A deterministic contracts

Landed contracts remain:

```text
test_bilibili_formal_adapter.py  11 tests
test_bilibili_http_gateway.py     9 tests
```

The HTTP-gateway fixtures now model the current uid-endpoint shape: uid may be
absent, status may be camelCase, roundStatus is handled explicitly, and an
explicit contradictory uid remains AMBIGUOUS.

Accepted complete Gate 1 baseline entering 1.3-4A is 157 tests. Expected complete
suite after the 20 Bilibili contracts remains 177 tests.

## 9. Acceptance — Gate 1.3-4A

```text
A. Gate 1.3-3 PASS / CLOSED                    PASS
B. Bilibili formal adapter core                PASS / CODE
C. uid identity rule frozen                    PASS / CODE
D. evidence-backed 0/1/2 mapping frozen        PASS / CODE
E. failure -> UNKNOWN                          PASS / CONTRACT
F. no legacy runtime import                    PASS / CONTRACT
G. Bilibili HTTP gateway                       PASS / CODE
H. getRoomInfoOld schema correction            PASS / CODE
I. dedicated formal-adapter contracts          PENDING / 11
J. dedicated HTTP-gateway contracts            PENDING / 9
K. complete Gate 1 suite                       PENDING / expected 177
L. provider-backed Bilibili LIVE evidence      PENDING
M. provider-backed Bilibili OFFLINE evidence   PENDING
```

Gate 1.3-4A remains CURRENT until I-M pass.

## 10. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
legacy platform_adapters imported into stage_letter runtime
list/recommendation absence -> OFFLINE
provider failure / timeout / parse error -> OFFLINE
Bilibili room id replacing stable uid identity
missing uid echo treated as fabricated identity evidence
Huya 0 -> OFFLINE without decisive ground-truth evidence
Douyu 0/3/4 guessed as decisive state
adapter mutating LiveSession / LiveEvent or notification eligibility
```
