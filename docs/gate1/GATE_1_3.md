# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 PASS / 1.3-2 PASS / 1.3-3 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)
- [`GATE_1_3_DOUYIN.md`](./GATE_1_3_DOUYIN.md)

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

## 3. Gate 1.3-1 — PASS

Accepted evidence:

```text
Gate 1.3-1 adapter contracts: 10 / 10 PASS
Complete Gate 1 suite:        121 / 121 PASS
```

The accepted contract remains:

```text
LivePlatformAdapter
  resolve_creator(input)
  get_creator_profile(account)
  get_live_snapshot(account)
```

with formal live truth exactly `LIVE / OFFLINE / UNKNOWN` and explicit registry
wiring only.

Gate 1.3-1: **PASS / CLOSED**.

## 4. Gate 1.3-2 — PASS

Accepted user-local evidence:

```text
Provider failure normalization contracts: 11 / 11 PASS
Complete Gate 1 suite:                132 / 132 PASS
```

The frozen rule is:

```text
provider failure / ambiguity -> UNKNOWN
```

including timeout, network errors, 401/403/404/429, captcha/auth challenges,
parse errors, schema drift, ambiguous results, and upstream failures. None may be
silently coerced to OFFLINE.

Gate 1.3-2: **PASS / CLOSED**.

## 5. Gate 1.3-3 — CURRENT

Landed assets:

```text
stage_letter/infrastructure/platforms/douyin.py
tests/gate1/test_douyin_formal_adapter.py
docs/gate1/GATE_1_3_DOUYIN.md
```

The formal Douyin adapter migrates only Gate 0A evidence-backed semantics:

```text
raw status 2 -> LIVE
raw status 4 -> OFFLINE
anything else -> UNKNOWN
```

Stable profile/sec_uid identity remains authoritative over historical room URLs.
Stale title/room metadata does not override explicit state. Provider failures or
identity mismatch remain UNKNOWN for live reads.

The adapter consumes provider transport through an injected
`DouyinProviderGateway`; it does not import the legacy top-level
`platform_adapters/*` package or Gate 0 experiments inward.

Twelve dedicated contracts are now landed. Starting from the accepted 132-test
baseline, the expected full Gate 1 count is 144 tests.

Gate 1.3-3 remains CURRENT after the static/local contracts; provider-backed
transport/probe evidence is still required before this slice closes PASS.

## 6. Legacy treatment

The existing top-level `platform_adapters/*` package remains legacy migration
debt. Formal `stage_letter/*` does not import it.

Concrete provider migrations copy only evidence-backed semantics into the formal
boundary; legacy runtime code is not wrapped inward as an authoritative
dependency.

## 7. Preserved inherited status

```text
Gate 0A    DEGRADED / deferred lifecycle evidence gap
Gate 0B-E  PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   CURRENT
```

## 8. Current progression

```text
Gate 1.3-1  PASS / 10 dedicated + 121 full Gate 1 evidence
Gate 1.3-2  PASS / 11 dedicated + 132 full Gate 1 evidence
Gate 1.3-3  CURRENT / formal Douyin adapter + 12 contracts landed; local evidence pending
Gate 1.3-4  NOT STARTED
Gate 1.3-5  NOT STARTED
Gate 1.3    CURRENT
```

## 9. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
provider-specific statuses added to formal LiveStatus
failure/ambiguity converted to OFFLINE by default
adapter mutating canonical session/event state
adapter generating Stage Letter persistence ids
formal application importing provider/infrastructure code
formal infrastructure importing legacy platform_adapters as runtime dependency
historical room URL replacing stable creator identity
stale metadata overriding explicit provider status
fabricating Gate 0A lifecycle evidence
```
