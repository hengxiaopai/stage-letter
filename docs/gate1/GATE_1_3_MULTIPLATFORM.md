# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A PASS / 1.3-4B HUYA PROVIDER CONTROLS PASS / LOCAL REGRESSION PENDING**

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

Accepted user-local evidence after the carousel false-positive correction:

```text
formal Bilibili adapter contracts       11 / 11 PASS
Bilibili HTTP gateway contracts          9 / 9 PASS
complete Gate 1 suite                   177 / 177 PASS
provider-backed LIVE control                  PASS
corrected provider-backed OFFLINE control     PASS
```

The decisive controls proved that Stage Letter must distinguish actual creator
broadcasting from carousel/replay activity. The final formal creator-live truth is:

```text
actual creator live status 1 -> LIVE
actual creator live status 0 -> OFFLINE
carousel/room status 2       -> OFFLINE for creator-live truth
roundStatus=1 alone          -> never promotes to LIVE
other / missing / failure    -> UNKNOWN
```

Stable Bilibili uid/space identity remains canonical; room id is live-room
metadata. Provider failures, parse failures, ambiguity, and identity mismatch do
not become OFFLINE.

The earlier failed OFFLINE control was useful negative evidence: it exposed the
carousel false-positive, the implementation was corrected, the deterministic
suite stayed green, and the same independently checked OFFLINE control then
returned `expectation_match=true`.

Result: **Gate 1.3-4A PASS / CLOSED**.

## 3. Gate 1.3-4B — Huya CURRENT

### Evidence authority

The older Huya capacity note from 2026-08-02 recorded repeated decisive LIVE
samples with `eLiveStatus=2` but lacked a decisive OFFLINE control. A later
2026-08-14 correction in the legacy Huya adapter recorded a stronger current
cross-signal after a real false-positive incident:

```text
eLiveStatus=2 <-> body.liveStatus-on  -> LIVE
eLiveStatus=1 <-> body.liveStatus-off -> OFFLINE
```

That later correction supersedes the older broad assumption that 1/2/3 were all
live and is more specific than the stale capacity-table `0 -> OFFLINE` note.
Formal Gate 1.3 therefore freezes only the later observed values:

```text
integer 2        -> LIVE
integer 1        -> OFFLINE
"liveStatus-on"  -> LIVE   # explicit body-class fallback
"liveStatus-off" -> OFFLINE
0 / 3 / other    -> UNKNOWN
failure          -> UNKNOWN
```

No `0 -> OFFLINE` rule is promoted without separate evidence.

### Formal Huya runtime landed

```text
stage_letter/infrastructure/platforms/huya.py
stage_letter/infrastructure/platforms/huya_http.py
scripts/gate13_huya_provider_probe.py
tests/gate1/test_huya_formal_adapter.py
tests/gate1/test_huya_http_gateway.py
```

Current evidence exposes Huya room id as the stable monitor key available to
Stage Letter. The formal adapter therefore uses room id as `platform_user_id` and
`room_id` rather than fabricating an unproven creator uid.

The provider transport reads:

```text
https://m.huya.com/<room_id>
```

and only accepts evidence-backed status signals. If both body class and
`eLiveStatus` are present they must agree; otherwise the result is AMBIGUOUS and
becomes UNKNOWN rather than choosing one silently.

The gateway deliberately does not use recommendation/list absence as OFFLINE.
Transport failures, missing status fields, HTML drift, timeout, and rate limiting
remain non-decisive provider failures.

### Current provider controls — PASS

On 2026-08-19 the operator independently checked one current LIVE room and one
current OFFLINE room, then exercised the formal provider chain:

```text
room 30764401
expected            LIVE
observed            LIVE
expectation_match   true
source              huya.mobile_html

room 30457578
expected            OFFLINE
observed            OFFLINE
expectation_match   true
source              huya.mobile_html
```

Result:

```text
provider-backed Huya LIVE control     PASS
provider-backed Huya OFFLINE control  PASS
```

Both outputs carried the same title metadata (`【预告】1日17点iG vs LNG 德杯半决赛`)
while their decisive live states differed. This is explicit evidence that Huya
title extraction is **non-canonical metadata** and must never influence live-state
truth. In later API/UI integration, OFFLINE title metadata must not be presented
as a current-live title; title correctness remains a separate metadata concern.

### Deterministic contracts

Landed:

```text
test_huya_formal_adapter.py  10 tests
test_huya_http_gateway.py    10 tests
```

Accepted complete Gate 1 baseline entering 1.3-4B is 177 tests. Expected complete
suite after the 20 Huya contracts is 197 tests.

### Acceptance — Gate 1.3-4B

```text
A. Gate 1.3-4A Bilibili PASS / CLOSED          PASS
B. formal Huya adapter core                     PASS / CODE
C. Huya mobile HTML gateway                     PASS / CODE
D. 2 -> LIVE / 1 -> OFFLINE freeze              PASS / CODE
E. 0 / 3 / unsupported -> UNKNOWN               PASS / CODE
F. failure / body-field conflict -> UNKNOWN     PASS / CONTRACT
G. no legacy runtime import                     PASS / CONTRACT
H. current provider-backed Huya LIVE control    PASS
I. current provider-backed Huya OFFLINE control PASS
J. dedicated formal-adapter contracts           PENDING / 10
K. dedicated HTTP-gateway contracts             PENDING / 10
L. complete Gate 1 suite                        PENDING / expected 197
```

Gate 1.3-4B remains CURRENT until J-L pass. No additional real Huya provider
control is required for this slice if the deterministic regression remains green.

## 4. Gate 1.3-4C — Douyu boundary

The existing evidence record supports:

```text
show_status = 1 -> LIVE
show_status = 2 -> OFFLINE
```

Values `0 / 3 / 4` remain ambiguous without additional evidence. Recommendation
or directory absence must never be treated as OFFLINE. Formal Douyu migration
starts only after Gate 1.3-4B closes.

## 5. Current progression

```text
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  CURRENT / provider LIVE+OFFLINE controls PASS; 10+10+197 local regression pending
Gate 1.3-4C  NOT STARTED
Gate 1.3-4D  NOT STARTED
```

## 6. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy platform_adapters imported into stage_letter runtime
provider failure / timeout / parse error -> OFFLINE
list/recommendation absence -> OFFLINE
Huya 0 / 3 guessed as OFFLINE
Huya body/eLiveStatus conflict silently accepted
fabricated Huya creator uid
Huya title metadata treated as live-state truth
Bilibili carousel/replay activity -> creator LIVE
Douyu 0/3/4 guessed as decisive state
adapter mutating LiveSession / LiveEvent or notification eligibility
```
