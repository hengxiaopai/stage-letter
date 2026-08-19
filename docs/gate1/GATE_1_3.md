# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 PASS / 1.3-2 PASS / 1.3-3 PASS / 1.3-4 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)
- [`GATE_1_3_DOUYIN.md`](./GATE_1_3_DOUYIN.md)
- [`GATE_1_3_MULTIPLATFORM.md`](./GATE_1_3_MULTIPLATFORM.md)

## 1. Goal

Gate 1.3 introduces the formal platform-adapter boundary that converts external
provider responses into normalized Stage Letter facts without allowing provider
vocabulary or transport failures to become canonical domain truth.

```text
provider implementation
  -> LivePlatformAdapter
      -> ResolvedCreator / CreatorProfileSnapshot / LiveSnapshot
          -> application orchestration
              -> later observation/state pipeline
```

Adapters emit normalized facts only. They do not persist canonical
LiveSession/LiveEvent truth or decide notification eligibility.

## 2. Gate 1.3 slices

```text
Gate 1.3-1  Adapter Contract + Registry Freeze
Gate 1.3-2  Provider Error / Ambiguity Normalization
Gate 1.3-3  Douyin Formal Adapter Migration
Gate 1.3-4  Bilibili / Huya / Douyu Formal Adapter Migration
Gate 1.3-5  Adapter Regression / Acceptance
```

## 3. Accepted slices

```text
Gate 1.3-1  PASS / 10 dedicated + 121 full Gate 1 evidence
Gate 1.3-2  PASS / 11 dedicated + 132 full Gate 1 evidence
Gate 1.3-3  PASS / CLOSED
```

Gate 1.3-3 accepted evidence:

```text
Douyin formal-adapter contracts     12 / 12 PASS
StreamGet gateway contracts         10 / 10 PASS
provider-probe CLI contracts         3 / 3 PASS
complete Gate 1 suite              157 / 157 PASS
real LIVE provider probe                 PASS
real OFFLINE provider probe              PASS
```

Formal Douyin transport:

```text
StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot
```

with integer `2 -> LIVE`, integer `4 -> OFFLINE`, all other/failure outcomes
remaining UNKNOWN. Gate 0A remains DEGRADED for its separate deferred lifecycle
evidence gap.

## 4. Gate 1.3-4 — CURRENT

```text
Gate 1.3-4A  Bilibili  PASS / CLOSED
Gate 1.3-4B  Huya      CURRENT
Gate 1.3-4C  Douyu     NOT STARTED
Gate 1.3-4D  cross-platform acceptance NOT STARTED
```

### Gate 1.3-4A Bilibili — accepted

Accepted user-local evidence:

```text
formal adapter contracts      11 / 11 PASS
HTTP gateway contracts         9 / 9 PASS
complete Gate 1 suite        177 / 177 PASS
provider LIVE control              PASS
corrected provider OFFLINE control PASS
```

The provider controls corrected a carousel false-positive. Final Bilibili
creator-live semantics are:

```text
actual creator live status 1 -> LIVE
actual creator live status 0 -> OFFLINE
carousel / replay status 2   -> OFFLINE for creator-live truth
roundStatus=1 alone          -> never promotes to LIVE
failure / ambiguity          -> UNKNOWN
```

Stable Bilibili uid/space identity remains canonical over room ids.

### Gate 1.3-4B Huya — provider controls accepted, local regression pending

Landed:

```text
stage_letter/infrastructure/platforms/huya.py
stage_letter/infrastructure/platforms/huya_http.py
scripts/gate13_huya_provider_probe.py
tests/gate1/test_huya_formal_adapter.py
tests/gate1/test_huya_http_gateway.py
```

A later 2026-08-14 project correction provides stronger Huya evidence than the
older capacity note:

```text
eLiveStatus=2 <-> body.liveStatus-on  -> LIVE
eLiveStatus=1 <-> body.liveStatus-off -> OFFLINE
```

Formal mapping therefore freezes only:

```text
2 / liveStatus-on  -> LIVE
1 / liveStatus-off -> OFFLINE
0 / 3 / other      -> UNKNOWN
failure/conflict   -> UNKNOWN
```

The gateway reads `https://m.huya.com/<room_id>`. Current evidence exposes room id
as the stable monitor key available to Stage Letter, so the formal adapter uses it
without fabricating a provider creator uid. Body class and `eLiveStatus` must agree
when both are present; disagreement becomes AMBIGUOUS/UNKNOWN.

Accepted provider-backed controls on 2026-08-19:

```text
room 30764401 -> expected LIVE    -> observed LIVE    -> expectation_match=true
room 30457578 -> expected OFFLINE -> observed OFFLINE -> expectation_match=true
source: huya.mobile_html
```

Both controls emitted the same title metadata while the decisive states differed.
That title is therefore non-canonical metadata and must not influence state truth
or be presented as a current-live title for an OFFLINE account.

New deterministic contracts:

```text
formal Huya adapter  10
Huya HTTP gateway    10
```

The accepted entering baseline is 177 tests; expected current complete Gate 1
count is 197 tests. Gate 1.3-4B now needs only the local deterministic regression:

```text
10 / 10 formal Huya adapter contracts
10 / 10 Huya HTTP gateway contracts
197 / 197 complete Gate 1 suite
```

No additional real Huya provider control is required for this slice if those
regressions remain green.

### Douyu boundary

Existing evidence supports `show_status=1 -> LIVE` and `show_status=2 -> OFFLINE`.
Values 0/3/4 and directory/list absence remain non-decisive until Gate 1.3-4C.

## 5. Legacy treatment

The existing top-level `platform_adapters/*` package remains legacy migration
debt. Formal `stage_letter/*` does not import it.

Concrete provider migrations copy only evidence-backed semantics into the formal
boundary; legacy runtime code is not wrapped inward as an authoritative
dependency.

## 6. Preserved inherited status

```text
Gate 0A    DEGRADED / deferred lifecycle evidence gap
Gate 0B-E  PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   CURRENT
```

## 7. Current progression

```text
Gate 1.3-1   PASS
Gate 1.3-2   PASS
Gate 1.3-3   PASS / CLOSED
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  CURRENT / provider LIVE+OFFLINE controls PASS; 10+10+197 local regression pending
Gate 1.3-4C  NOT STARTED
Gate 1.3-4D  NOT STARTED
Gate 1.3-5   NOT STARTED
Gate 1.3     CURRENT
```

## 8. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
provider-specific statuses added to formal LiveStatus
failure/ambiguity converted to OFFLINE by default
adapter mutating canonical session/event state
adapter generating Stage Letter persistence ids
formal application importing provider/infrastructure code
formal infrastructure importing legacy platform_adapters as runtime dependency
carousel/replay activity treated as creator LIVE
list/recommendation absence treated as OFFLINE
Huya 0 / 3 guessed as OFFLINE
Huya body/eLiveStatus conflict silently accepted
fabricated Huya creator uid
Huya title metadata treated as live-state truth
stale metadata overriding explicit provider status
fabricating Gate 0A lifecycle evidence
```
