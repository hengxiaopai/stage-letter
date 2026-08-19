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

The accepted formal Douyin transport is:

```text
StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot
```

with integer `2 -> LIVE`, integer `4 -> OFFLINE`, all other/failure outcomes
remaining UNKNOWN. Gate 0A remains DEGRADED for its separate deferred lifecycle
evidence gap.

## 4. Gate 1.3-4 — CURRENT

Gate 1.3-4 is internally sequenced:

```text
Gate 1.3-4A  Bilibili formal adapter + provider evidence       CURRENT
Gate 1.3-4B  Huya formal adapter + OFFLINE evidence resolution NOT STARTED
Gate 1.3-4C  Douyu formal adapter + provider evidence          NOT STARTED
Gate 1.3-4D  cross-platform regression / registry acceptance   NOT STARTED
```

### Bilibili formal runtime landed

```text
stage_letter/infrastructure/platforms/bilibili.py
stage_letter/infrastructure/platforms/bilibili_http.py
scripts/gate13_bilibili_provider_probe.py
tests/gate1/test_bilibili_formal_adapter.py
tests/gate1/test_bilibili_http_gateway.py
```

The formal Bilibili identity is uid/space identity rather than room id. The
frozen evidence-backed mapping is:

```text
integer live_status 0 -> OFFLINE
integer live_status 1 -> LIVE
integer live_status 2 -> LIVE / carousel
bool/string lookalikes/other -> UNKNOWN
failure / ambiguity -> UNKNOWN
```

The HTTP gateway resolves a live-room URL through `room_init` to stable uid and
uses `getRoomInfoOld` for uid-based live facts. Provider failures, nonzero codes,
parse/schema failures, and uid mismatch do not become OFFLINE.

Twenty Bilibili contracts are now landed:

```text
formal adapter  11
HTTP gateway     9
```

The accepted entering Gate 1 baseline is 157 tests, so the current expected full
suite is 177 tests.

Huya and Douyu are deliberately not copied wholesale from legacy adapters. The
existing Huya evidence explicitly lacks decisive OFFLINE ground truth, so
`eLiveStatus=0 -> OFFLINE` must be proven before becoming formal canonical truth.
The existing Douyu record supports decisive `show_status=1 -> LIVE` and
`show_status=2 -> OFFLINE`, while 0/3/4 remain ambiguous without further evidence.

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
Gate 1.3-4A  CURRENT / Bilibili core+HTTP gateway landed; 20 local contracts + provider evidence pending
Gate 1.3-4B  NOT STARTED
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
list/recommendation absence treated as OFFLINE
Huya OFFLINE promoted without decisive evidence
stale metadata overriding explicit provider status
fabricating Gate 0A lifecycle evidence
```
