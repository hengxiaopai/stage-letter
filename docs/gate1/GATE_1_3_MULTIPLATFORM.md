# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **PASS / CLOSED**

Entry authority: Gate 1.3-3 PASS / CLOSED.

## 1. Slice result

```text
Gate 1.3-4A  Bilibili formal adapter + provider evidence       PASS / CLOSED
Gate 1.3-4B  Huya formal adapter + provider evidence           PASS / CLOSED
Gate 1.3-4C  Douyu formal adapter + provider evidence          PASS / CLOSED
Gate 1.3-4D  cross-platform registry acceptance                PASS / CLOSED
Gate 1.3-4   PASS / CLOSED
```

No platform inherits another platform's state mapping.

## 2. Bilibili accepted evidence

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

Stable Bilibili uid/space identity remains canonical; room id is metadata. The current provider controls corrected a real carousel false-positive before acceptance.

## 3. Huya accepted evidence

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

Formal truth:

```text
integer 2        -> LIVE
integer 1        -> OFFLINE
"liveStatus-on"  -> LIVE
"liveStatus-off" -> OFFLINE
0 / 3 / other    -> UNKNOWN
failure/conflict -> UNKNOWN
```

Room id is the proven monitor key available to this slice; no unproven creator uid is fabricated. Title metadata is non-canonical and does not participate in state truth.

## 4. Douyu accepted evidence

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

Formal creator-live truth:

```text
integer show_status 1 -> LIVE
integer show_status 2 -> OFFLINE
0 / 3 / 4 / other     -> UNKNOWN
string/bool drift      -> UNKNOWN
videoLoop alone        -> no decisive truth
provider failure       -> UNKNOWN
```

Multiple explicit state fields must agree or the result is AMBIGUOUS/UNKNOWN. Recommendation/list absence and replay/loop activity do not become creator-live truth.

## 5. Cross-platform registry acceptance — PASS / CLOSED

Landed:

```text
stage_letter/infrastructure/platforms/factory.py
stage_letter/infrastructure/platforms/__init__.py
tests/gate1/test_platform_registry_acceptance.py
```

`build_formal_adapter_registry()` constructs a fresh explicit registry containing exactly:

```text
bilibili -> BilibiliFormalAdapter(BilibiliHttpGateway)
douyin   -> DouyinFormalAdapter(StreamGetDouyinGateway)
douyu    -> DouyuFormalAdapter(DouyuHttpGateway)
huya     -> HuyaFormalAdapter(HuyaHttpGateway)
```

Construction performs no provider request. StreamGet remains lazily imported by the Douyin gateway.

Accepted user-local evidence:

```text
platform registry acceptance contracts   8 / 8 PASS
complete Gate 1 suite                   225 / 225 PASS
```

The contracts verify exact platform membership, structural `LivePlatformAdapter` compatibility, registry key/platform agreement, formal adapter types only, no eager StreamGet import, fresh instances per build, explicit unknown-platform failure, and no legacy/session/event/notification ownership.

Result: **Gate 1.3-4D PASS / CLOSED**.

## 6. Gate 1.3-4 exit

```text
Gate 1.3-4  PASS / CLOSED
Gate 1.3-5  CURRENT / final adapter-framework acceptance
```

No additional provider LIVE/OFFLINE controls are required solely for Gate 1.3-5 unless deterministic acceptance reveals a material semantic or transport regression.

## 7. Stop rules preserved

The accepted implementation must continue to reject:

```text
legacy platform_adapters imported into formal runtime
provider failure / timeout / parse error -> OFFLINE
list/recommendation absence -> OFFLINE
Bilibili replay/carousel -> creator LIVE
Huya 0 / 3 guessed as OFFLINE
Huya conflicting status evidence silently accepted
Douyu 0 / 3 / 4 guessed as decisive state
Douyu videoLoop/replay -> creator LIVE
fabricated provider creator uid
registry construction performing provider I/O
adapter ownership of LiveSession / LiveEvent / notification eligibility
```
