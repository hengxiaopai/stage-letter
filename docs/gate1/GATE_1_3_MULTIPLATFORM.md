# Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration

Status: **CURRENT / 1.3-4A PASS / 1.3-4B PASS / 1.3-4C DOUYU PROVIDER CONTROLS PASS / LOCAL REGRESSION PENDING**

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

The two provider controls emitted identical title metadata while their live states
differed. Huya title extraction is therefore non-canonical metadata and must not
participate in live-state truth or be shown as a current-live title for OFFLINE.

Result: **Gate 1.3-4B PASS / CLOSED**.

## 4. Gate 1.3-4C — Douyu CURRENT

### Evidence authority

The accepted Gate 0B record establishes decisive current-state values:

```text
show_status = 1 -> LIVE
show_status = 2 -> OFFLINE
```

Values `0 / 3 / 4` remain ambiguous. Directory/recommendation absence is not
OFFLINE evidence.

The legacy adapter also contained generic `videoLoop=1` and `isLiveBroadcast`
fallbacks. Those are deliberately **not** promoted into formal creator-live truth
in Gate 1.3-4C: Stage Letter's LIVE means the creator is actually broadcasting,
and the Bilibili false-positive already demonstrated why replay/loop activity
must not be silently treated as creator LIVE.

Formal Douyu truth is therefore frozen as:

```text
integer show_status 1 -> LIVE
integer show_status 2 -> OFFLINE
0 / 3 / 4 / other     -> UNKNOWN
string/bool drift      -> UNKNOWN
videoLoop alone        -> no decisive truth
provider failure       -> UNKNOWN
```

### Formal Douyu runtime landed

```text
stage_letter/infrastructure/platforms/douyu.py
stage_letter/infrastructure/platforms/douyu_http.py
scripts/gate13_douyu_provider_probe.py
tests/gate1/test_douyu_formal_adapter.py
tests/gate1/test_douyu_http_gateway.py
```

Current evidence exposes Douyu room id as the stable monitor key available to
Stage Letter, so the formal adapter uses room id as both platform_user_id and
room_id without fabricating a separate creator uid.

The provider gateway reads:

```text
https://www.douyu.com/<room_id>
```

and accepts only explicit `show_status` / `showStatus` numeric evidence. Escaped
and unescaped HTML forms are supported. If multiple explicit status fields are
present and disagree, the result is AMBIGUOUS/UNKNOWN rather than choosing one.

`videoLoop`, recommendation-list presence/absence, and generic weak fallbacks do
not create canonical LIVE/OFFLINE truth. Transport failures, missing fields,
HTML/schema drift, timeout and rate limiting remain provider failures.

### Current provider controls — PASS

On 2026-08-19 the operator independently checked one current LIVE room and one
current OFFLINE room, then exercised the formal provider chain:

```text
room 74751
expected            LIVE
observed            LIVE
expectation_match   true
source              douyu.desktop_html

room 6512
expected            OFFLINE
observed            OFFLINE
expectation_match   true
source              douyu.desktop_html
```

Result:

```text
provider-backed Douyu LIVE control     PASS
provider-backed Douyu OFFLINE control  PASS
```

The OFFLINE control still carried page/title metadata. As with Huya, metadata is
non-canonical and must not influence live-state truth or be rendered as a current
live title for an OFFLINE account.

### Deterministic contracts

Landed:

```text
test_douyu_formal_adapter.py  10 tests
test_douyu_http_gateway.py    10 tests
```

Accepted complete Gate 1 baseline entering 1.3-4C is 197 tests. Expected complete
suite after the 20 Douyu contracts is 217 tests.

### Acceptance — Gate 1.3-4C

```text
A. Gate 1.3-4B Huya PASS / CLOSED               PASS
B. formal Douyu adapter core                     PASS / CODE
C. Douyu desktop HTML gateway                    PASS / CODE
D. show_status 1 -> LIVE / 2 -> OFFLINE         PASS / CODE
E. 0 / 3 / 4 / unsupported -> UNKNOWN           PASS / CODE
F. videoLoop alone not creator-live truth        PASS / CONTRACT
G. failure / conflicting fields -> UNKNOWN      PASS / CONTRACT
H. no legacy runtime import                      PASS / CONTRACT
I. current provider-backed Douyu LIVE control    PASS
J. current provider-backed Douyu OFFLINE control PASS
K. dedicated formal-adapter contracts            PENDING / 10
L. dedicated HTTP-gateway contracts              PENDING / 10
M. complete Gate 1 suite                         PENDING / expected 217
```

Gate 1.3-4C remains CURRENT until K-M pass. No additional real Douyu provider
control is required for this slice if deterministic regression remains green.

## 5. Current progression

```text
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  PASS / CLOSED
Gate 1.3-4C  CURRENT / provider LIVE+OFFLINE controls PASS; 10+10+217 local regression pending
Gate 1.3-4D  NOT STARTED
```

## 6. Stop rules

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
conflicting Douyu explicit status fields silently accepted
fabricated provider creator uid
adapter mutating LiveSession / LiveEvent or notification eligibility
```
