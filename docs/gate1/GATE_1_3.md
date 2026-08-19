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

## 3. Accepted slices

```text
Gate 1.3-1  PASS / 10 dedicated + 121 full Gate 1 evidence
Gate 1.3-2  PASS / 11 dedicated + 132 full Gate 1 evidence
```

Formal live truth remains exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

Failure/ambiguity remains UNKNOWN and never silently becomes OFFLINE.

## 4. Gate 1.3-3 — CURRENT

Accepted semantic migration evidence:

```text
Douyin formal adapter contracts: 12 / 12 PASS
Complete Gate 1 suite:          144 / 144 PASS
```

The formal adapter preserves only Gate 0A evidence-backed semantics:

```text
raw integer 2 -> LIVE
raw integer 4 -> OFFLINE
anything else / failure -> UNKNOWN
```

Stable profile/sec_uid identity remains authoritative over historical room URLs.

Provider transport is landed through:

```text
stage_letter/infrastructure/platforms/douyin_streamget.py
tests/gate1/test_douyin_streamget_gateway.py
scripts/gate13_douyin_provider_probe.py
```

The runtime chain is:

```text
StreamGetDouyinGateway
  -> DouyinProviderGateway
      -> DouyinFormalAdapter
          -> LiveSnapshot
```

The new gateway uses StreamGet PROFILE/sec_uid reads only, lazily imports
StreamGet on real provider access, and does not import legacy
`platform_adapters/*`, `experiments/*`, `core/*`, `api/*`, or `workers/*` inward.

The first operator LIVE/OFFLINE probe attempts returned UNKNOWN because the CLI
identity argument was copied as a Markdown-wrapped link rather than a raw Douyin
profile URL. That failed before decisive provider evidence and therefore counts as
probe-harness/input evidence only, not a LIVE/OFFLINE result.

The CLI is now hardened to unwrap a Markdown link only when its visible URL and
target URL are identical, while the formal gateway remains strict. A mismatched
Markdown target is rejected. Three dedicated probe-CLI contracts were added.

Current pending evidence is therefore:

```text
10 / 10 StreamGet gateway contracts
3 / 3 provider-probe CLI normalization contracts
157 / 157 complete Gate 1 suite
one independently verified LIVE provider probe
one independently verified OFFLINE provider probe
```

The real probes must use current independently checked creator state. They are
technical transport evidence only and do not upgrade Gate 0A lifecycle evidence
or production authorization.

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
Gate 1.3-1  PASS
Gate 1.3-2  PASS
Gate 1.3-3  CURRENT / adapter core PASS; StreamGet gateway + hardened probe landed; local/provider evidence pending
Gate 1.3-4  NOT STARTED
Gate 1.3-5  NOT STARTED
Gate 1.3    CURRENT
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
historical room URL replacing stable creator identity
stale metadata overriding explicit provider status
provider cookie/secret printed by probe
fabricating Gate 0A lifecycle evidence
```
