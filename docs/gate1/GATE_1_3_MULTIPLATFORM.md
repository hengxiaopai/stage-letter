# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A BILIBILI CORE LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.3-3 PASS / CLOSED.

## 1. Slice plan

Gate 1.3-4 is split internally so each platform can preserve only evidence it has
actually established:

```text
Gate 1.3-4A  Bilibili formal adapter + provider evidence
Gate 1.3-4B  Huya formal adapter + missing OFFLINE evidence resolution
Gate 1.3-4C  Douyu formal adapter + provider evidence
Gate 1.3-4D  cross-platform regression / registry acceptance
```

No platform is allowed to inherit another platform's state mapping.

## 2. Bilibili evidence authority

The accepted legacy evidence record establishes:

```text
stable external identity: Bilibili uid / space profile
live_status = 0 -> OFFLINE
live_status = 1 -> LIVE
live_status = 2 -> LIVE / carousel
other / missing / failure -> not decisive canonical truth
```

Gate 0B soak evidence included both decisive LIVE and OFFLINE paths, with 139
ONLINE and 91 OFFLINE observations in the recorded soak matrix. It still lacked a
real same-creator transition, so this migration does not claim lifecycle proof.

Room id is treated as live-room/navigation metadata; uid remains the formal
PlatformAccount identity.

## 3. Bilibili formal core

Landed:

```text
stage_letter/infrastructure/platforms/bilibili.py
tests/gate1/test_bilibili_formal_adapter.py
```

The adapter implements the application-owned `LivePlatformAdapter` contract via
an injected `BilibiliProviderGateway`:

```text
resolve_identity(input) -> BilibiliIdentityRecord
fetch_profile(uid)      -> BilibiliProfileRecord
fetch_live(uid)         -> BilibiliLiveRecord
```

It does not import legacy `platform_adapters/*`, `experiments/*`, `core/*`,
`api/*`, or `workers/*`.

Canonical mapping is intentionally strict by type:

```text
integer 0 -> OFFLINE
integer 1 -> LIVE
integer 2 -> LIVE
string "0" / "1" / "2" -> UNKNOWN
other values -> UNKNOWN
```

Provider failure, timeout, rate limiting, schema drift, and identity mismatch
remain UNKNOWN for live reads.

## 4. Huya evidence boundary before migration

The existing evidence record currently proves repeated LIVE observations with
`eLiveStatus=2`, but explicitly records that real OFFLINE ground truth had not yet
been established in the Gate 0B sample.

Therefore Gate 1.3-4B must not blindly promote the legacy table's `0 -> OFFLINE`
rule to formal canonical truth until a decisive current OFFLINE sample is verified.
At minimum:

```text
proven eLiveStatus=2 -> LIVE
failure / missing / unsupported -> UNKNOWN
0 -> OFFLINE requires provider-backed ground-truth confirmation in 1.3-4B
```

## 5. Douyu evidence boundary before migration

The existing evidence record establishes both paths:

```text
show_status = 1 -> LIVE
show_status = 2 -> OFFLINE
```

It also records `0 / 3 / 4` as ambiguous without additional evidence and warns
that list/recommendation absence must not be treated as OFFLINE. Gate 1.3-4C will
preserve that conservative boundary.

## 6. Gate 1.3-4A contracts

`tests/gate1/test_bilibili_formal_adapter.py` adds eleven checks covering:

```text
formal structural compatibility
uid as canonical external identity
profile identity consistency
live_status 1 -> LIVE
live_status 2 -> LIVE / carousel
live_status 0 -> OFFLINE
unrecognized/type-drift values -> UNKNOWN
provider failure -> UNKNOWN
timeout/network -> UNKNOWN
live identity mismatch -> UNKNOWN
no legacy/state/session/event/commit ownership
```

Accepted complete Gate 1 baseline entering 1.3-4A is 157 tests. Expected count
after these contracts is 168.

## 7. Acceptance — Gate 1.3-4A

```text
A. Gate 1.3-3 PASS / CLOSED                    PASS
B. Bilibili formal adapter core                PASS / CODE
C. uid identity rule frozen                    PASS / CODE
D. evidence-backed 0/1/2 mapping frozen        PASS / CODE
E. failure -> UNKNOWN                          PASS / CONTRACT
F. no legacy runtime import                    PASS / CONTRACT
G. dedicated Bilibili adapter contracts        PENDING / 11
H. complete Gate 1 suite                       PENDING / expected 168
I. provider-backed Bilibili LIVE evidence      PENDING
J. provider-backed Bilibili OFFLINE evidence   PENDING
```

Gate 1.3-4A remains CURRENT until G-J pass.

## 8. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
legacy platform_adapters imported into stage_letter runtime
list/recommendation absence -> OFFLINE
provider failure / timeout / parse error -> OFFLINE
Bilibili room id replacing stable uid identity
Huya 0 -> OFFLINE without decisive ground-truth evidence
Douyu 0/3/4 guessed as decisive state
adapter mutating LiveSession / LiveEvent or notification eligibility
```
