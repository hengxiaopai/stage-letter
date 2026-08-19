# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A PASS / 1.3-4B PASS / 1.3-4C PASS / 1.3-4D CURRENT**

Entry authority: Gate 1.3-3 PASS / CLOSED.

## 1. Slice plan

```text
Gate 1.3-4A  Bilibili formal adapter + provider evidence
Gate 1.3-4B  Huya formal adapter + provider evidence
Gate 1.3-4C  Douyu formal adapter + provider evidence
Gate 1.3-4D  cross-platform regression / registry acceptance
```

No platform inherits another platform's state mapping.

## 2. Gate 1.3-4A — Bilibili PASS / CLOSED

Accepted user-local evidence:

```text
formal Bilibili adapter contracts       11 / 11 PASS
Bilibili HTTP gateway contracts          9 / 9 PASS
complete Gate 1 suite                   177 / 177 PASS
provider-backed LIVE control                  PASS
corrected provider-backed OFFLINE control     PASS
```

Final creator-live truth:

```text
actual creator live status 1 -> LIVE
actual creator live status 0 -> OFFLINE
carousel / replay status 2   -> OFFLINE for creator-live truth
roundStatus=1 alone          -> never promotes to LIVE
other / missing / failure    -> UNKNOWN
```

Stable Bilibili uid/space identity remains canonical; room id is metadata.

Result: **Gate 1.3-4A PASS / CLOSED**.

## 3. Gate 1.3-4B — Huya PASS / CLOSED

Accepted user-local evidence:

```text
formal Huya adapter contracts      10 / 10 PASS
Huya HTTP gateway contracts        10 / 10 PASS
complete Gate 1 suite             197 / 197 PASS
provider-backed LIVE control            PASS
provider-backed OFFLINE control         PASS
```

Accepted provider controls:

```text
room 30764401 -> expected LIVE    -> observed LIVE    -> expectation_match=true
room 30457578 -> expected OFFLINE -> observed OFFLINE -> expectation_match=true
source: huya.mobile_html
```

Formal Huya state truth is:

```text
integer 2        -> LIVE
integer 1        -> OFFLINE
"liveStatus-on"  -> LIVE
"liveStatus-off" -> OFFLINE
0 / 3 / other    -> UNKNOWN
failure/conflict -> UNKNOWN
```

Current evidence exposes room id as the stable monitor key available to Stage
Letter; no unproven creator uid is fabricated. If body class and eLiveStatus are
both present they must agree or the result becomes AMBIGUOUS/UNKNOWN.

Provider title metadata is non-canonical and must not participate in live-state
truth or be shown as a current-live title for OFFLINE.

Result: **Gate 1.3-4B PASS / CLOSED**.

## 4. Gate 1.3-4C — Douyu PASS / CLOSED

Accepted user-local evidence:

```text
formal Douyu adapter contracts      10 / 10 PASS
Douyu HTTP gateway contracts        10 / 10 PASS
complete Gate 1 suite              217 / 217 PASS
provider-backed LIVE control             PASS
provider-backed OFFLINE control          PASS
```

Accepted provider controls:

```text
room 74751 -> expected LIVE    -> observed LIVE    -> expectation_match=true
room 6512  -> expected OFFLINE -> observed OFFLINE -> expectation_match=true
source: douyu.desktop_html
```

Formal creator-live truth remains:

```text
integer show_status 1 -> LIVE
integer show_status 2 -> OFFLINE
0 / 3 / 4 / other     -> UNKNOWN
string/bool drift      -> UNKNOWN
videoLoop alone        -> no decisive truth
provider failure       -> UNKNOWN
```

The gateway accepts only explicit `show_status` / `showStatus` numeric evidence.
Multiple explicit state fields must agree or the result is AMBIGUOUS/UNKNOWN.
Recommendation/directory absence and replay/loop activity do not become
creator-live truth. Room id remains the proven monitor key available to this
slice; no unproven provider creator uid is fabricated.

The OFFLINE control still emitted page/title metadata, reinforcing that provider
metadata is non-canonical and must not influence state truth.

Result: **Gate 1.3-4C PASS / CLOSED**.

## 5. Gate 1.3-4D — Cross-platform registry acceptance CURRENT

Landed:

```text
stage_letter/infrastructure/platforms/factory.py
tests/gate1/test_platform_registry_acceptance.py
stage_letter/infrastructure/platforms/__init__.py  # formal public surface updated
```

`build_formal_adapter_registry()` constructs a fresh explicit registry containing
exactly the four formal platforms:

```text
bilibili -> BilibiliFormalAdapter(BilibiliHttpGateway)
douyin   -> DouyinFormalAdapter(StreamGetDouyinGateway)
douyu    -> DouyuFormalAdapter(DouyuHttpGateway)
huya     -> HuyaFormalAdapter(HuyaHttpGateway)
```

Construction performs no provider request. StreamGet remains lazily imported by
the Douyin gateway, so building the registry does not require eager provider
runtime loading.

The cross-platform acceptance contracts verify:

```text
exact formal platform set
all entries structurally implement LivePlatformAdapter
registry key matches adapter.platform
only formal concrete adapter types are registered
StreamGet is not imported eagerly during registry construction
fresh registry/adapter instances are returned per build
unknown platform lookup remains explicit AdapterNotFoundError
factory has no legacy/state/session/event/notification ownership
```

Eight dedicated contracts are landed. The accepted complete Gate 1 baseline
entering 1.3-4D is 217 tests, so the expected complete suite is 225 tests.

### Acceptance — Gate 1.3-4D

```text
A. Gate 1.3-4A Bilibili PASS / CLOSED           PASS
B. Gate 1.3-4B Huya PASS / CLOSED               PASS
C. Gate 1.3-4C Douyu PASS / CLOSED              PASS
D. formal four-platform registry factory        PASS / CODE
E. exact supported-platform set frozen          PASS / CONTRACT
F. no eager provider I/O / StreamGet import     PASS / CONTRACT
G. no legacy runtime import                     PASS / CONTRACT
H. dedicated registry acceptance contracts      PENDING / 8
I. complete Gate 1 suite                        PENDING / expected 225
```

No additional provider LIVE/OFFLINE control is required for 1.3-4D if H-I remain
green; the per-platform provider evidence was accepted in 1.3-3 and 1.3-4A/B/C.

Gate 1.3-4D remains CURRENT until H-I pass.

## 6. Current progression

```text
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  PASS / CLOSED
Gate 1.3-4C  PASS / CLOSED
Gate 1.3-4D  CURRENT / formal registry factory + 8 acceptance contracts landed
```

## 7. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy platform_adapters imported into stage_letter runtime
provider failure / timeout / parse error -> OFFLINE
list/recommendation absence -> OFFLINE
Huya 0 / 3 guessed as OFFLINE
Huya title metadata treated as state truth
Bilibili carousel/replay activity -> creator LIVE
Douyu 0 / 3 / 4 guessed as decisive state
Douyu videoLoop/replay activity -> creator LIVE
conflicting explicit provider state silently accepted
fabricated provider creator uid
registry construction performing provider I/O
registry construction eagerly requiring StreamGet
adapter mutating LiveSession / LiveEvent or notification eligibility
```
