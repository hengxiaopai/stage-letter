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

Formal Douyin transport remains:

```text
StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot
```

with integer `2 -> LIVE`, integer `4 -> OFFLINE`, all other/failure outcomes
remaining UNKNOWN. Gate 0A remains DEGRADED for its separate deferred lifecycle
evidence gap.

## 4. Gate 1.3-4 — CURRENT

```text
Gate 1.3-4A  Bilibili  PASS / CLOSED
Gate 1.3-4B  Huya      PASS / CLOSED
Gate 1.3-4C  Douyu     CURRENT
Gate 1.3-4D  cross-platform acceptance NOT STARTED
```

### Bilibili accepted evidence

```text
formal adapter contracts      11 / 11 PASS
HTTP gateway contracts         9 / 9 PASS
complete Gate 1 suite        177 / 177 PASS
provider LIVE control              PASS
corrected provider OFFLINE control PASS
```

Final creator-live semantics keep replay/carousel separate from actual creator
broadcasting.

### Huya accepted evidence

```text
formal Huya adapter contracts  10 / 10 PASS
Huya HTTP gateway contracts    10 / 10 PASS
complete Gate 1 suite         197 / 197 PASS
provider LIVE control               PASS
provider OFFLINE control            PASS
```

Formal Huya mapping remains:

```text
2 / liveStatus-on  -> LIVE
1 / liveStatus-off -> OFFLINE
0 / 3 / other      -> UNKNOWN
failure/conflict   -> UNKNOWN
```

Huya room id is the proven stable monitor key available to this slice; no
unproven creator uid is fabricated. Provider title metadata is non-canonical and
does not participate in state truth.

### Gate 1.3-4C Douyu — current implementation

Landed:

```text
stage_letter/infrastructure/platforms/douyu.py
stage_letter/infrastructure/platforms/douyu_http.py
scripts/gate13_douyu_provider_probe.py
tests/gate1/test_douyu_formal_adapter.py
tests/gate1/test_douyu_http_gateway.py
```

The accepted historical evidence supports only:

```text
integer show_status 1 -> LIVE
integer show_status 2 -> OFFLINE
0 / 3 / 4 / other     -> UNKNOWN
failure                -> UNKNOWN
```

The formal gateway reads `https://www.douyu.com/<room_id>` and parses explicit
`show_status` / `showStatus` numeric evidence. Escaped and unescaped HTML forms
are supported. Multiple explicit status fields must agree or the result becomes
AMBIGUOUS/UNKNOWN.

The legacy `videoLoop=1` fallback is intentionally not promoted into creator-live
truth: loop/replay activity is not sufficient evidence that the creator is
actually broadcasting. Recommendation/directory absence also remains non-
decisive.

Current evidence exposes room id as the stable monitor key available to Stage
Letter, so the formal adapter uses it without inventing a provider creator uid.

New deterministic contracts:

```text
formal Douyu adapter  10
Douyu HTTP gateway    10
```

The accepted entering baseline is 197 tests; expected current complete Gate 1
count is 217 tests. Gate 1.3-4C still requires 10/10 + 10/10 + 217/217 local
regression plus one independently checked current LIVE control and one current
OFFLINE control.

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
Gate 1.3-4B  PASS / CLOSED
Gate 1.3-4C  CURRENT / Douyu core+HTTP gateway+probe landed; local/provider evidence pending
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
Huya title metadata treated as live-state truth
Douyu 0 / 3 / 4 guessed as decisive state
Douyu videoLoop/replay activity treated as creator LIVE
conflicting explicit Douyu state silently accepted
fabricated provider creator uid
stale metadata overriding explicit provider status
fabricating Gate 0A lifecycle evidence
```
