# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A BILIBILI PROVIDER SEMANTICS CORRECTED / FINAL LOCAL+OFFLINE REPROBE PENDING**

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

## 2. Bilibili evidence authority — corrected by current provider control

The inherited Gate 0B record had treated Bilibili room status `2` / carousel as
ONLINE. Gate 1.3-4A current ground-truth controls exposed that this is not correct
for Stage Letter's product meaning of **creator is actually broadcasting now**.

Current operator controls on 2026-08-19 established:

```text
uid 299312132  independently checked LIVE
provider result LIVE
expectation_match true

uid 8618005    independently checked not actually live
provider initially returned LIVE
expectation_match false
provider title resembled replay/upload content
```

The second control revealed a semantic bug in the formal transport: the
`getRoomInfoOld` response's separate `roundStatus=1` carousel/replay flag had been
promoted to raw status `2`, and the formal adapter then mapped `2 -> LIVE`.

That behavior would create a false positive for Stage Letter's P0 question
"is my creator live now?" and could eventually create a false LIVE_STARTED event.
It is therefore rejected.

The corrected formal truth is:

```text
actual creator live status 1 -> LIVE
actual creator live status 0 -> OFFLINE
room/carousel status 2       -> OFFLINE for creator-live truth
roundStatus=1 alone          -> never promotes to LIVE
other / missing / failure    -> UNKNOWN
```

Carousel/replay activity may remain provider metadata in future, but it is not a
canonical creator-live state.

## 3. Bilibili formal core

Landed:

```text
stage_letter/infrastructure/platforms/bilibili.py
tests/gate1/test_bilibili_formal_adapter.py
```

The adapter implements `LivePlatformAdapter` via an injected
`BilibiliProviderGateway` and keeps uid/space identity canonical over room ids.

Corrected mapping is strict by type:

```text
integer 1 -> LIVE
integer 0 -> OFFLINE
integer 2 -> OFFLINE / carousel is not creator-live
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

The transport uses:

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

`getRoomInfoOld` can omit uid in its data object. Missing echoed uid is therefore
not schema drift; an explicit contradictory uid remains AMBIGUOUS.

The current transport also keeps `roundStatus` separate from creator-live truth:

```text
liveStatus / live_status -> raw creator-live status
roundStatus              -> does not override liveStatus
```

This fixes the false-positive control without weakening failure handling.

## 5. Current provider evidence

Accepted decisive LIVE control:

```text
uid                 299312132
expected            LIVE
observed            LIVE
expectation_match   true
source              bilibili.getRoomInfoOld
room_id             26681116
```

The first OFFLINE control is intentionally **not accepted** because it exposed the
carousel false-positive defect:

```text
uid                 8618005
expected            OFFLINE
observed            LIVE
expectation_match   false
source              bilibili.getRoomInfoOld
room_id             6136246
```

After the semantic correction, the same independently checked OFFLINE control must
be re-run and produce OFFLINE before Gate 1.3-4A can close.

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

The same 20-test count is retained, but two semantics were corrected rather than
adding redundant tests:

```text
raw status 2 carousel -> OFFLINE
roundStatus=1 + liveStatus=0 -> raw creator status remains 0
```

Accepted complete Gate 1 baseline entering 1.3-4A is 157 tests. Expected complete
suite remains 177 tests.

## 9. Acceptance — Gate 1.3-4A

```text
A. Gate 1.3-3 PASS / CLOSED                    PASS
B. Bilibili formal adapter core                PASS / CODE
C. uid identity rule frozen                    PASS / CODE
D. creator-live semantics corrected            PASS / CODE
E. roundStatus cannot promote LIVE             PASS / CODE
F. failure -> UNKNOWN                          PASS / CONTRACT
G. no legacy runtime import                    PASS / CONTRACT
H. Bilibili HTTP gateway                       PASS / CODE
I. provider-backed Bilibili LIVE evidence      PASS
J. dedicated formal-adapter contracts          PENDING / 11 rerun
K. dedicated HTTP-gateway contracts            PENDING / 9 rerun
L. complete Gate 1 suite                       PENDING / expected 177
M. corrected Bilibili OFFLINE provider probe   PENDING / re-run uid 8618005
```

Gate 1.3-4A remains CURRENT until J-M pass.

## 10. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
legacy platform_adapters imported into stage_letter runtime
carousel/replay activity -> canonical LIVE
roundStatus overriding an explicit non-live creator status
list/recommendation absence -> OFFLINE
provider failure / timeout / parse error -> OFFLINE
Bilibili room id replacing stable uid identity
Huya 0 -> OFFLINE without decisive ground-truth evidence
Douyu 0/3/4 guessed as decisive state
adapter mutating LiveSession / LiveEvent or notification eligibility
```
