# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 PASS / 1.3-2 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)

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

Accepted local evidence:

```text
Gate 1.2 historical acceptance contracts: 6 / 6 PASS
Complete Gate 1 suite:                  121 / 121 PASS
Gate 1.3-1 adapter contracts:           10 / 10 PASS (included in full suite)
```

The earlier single full-suite failure was a stale Gate 1.2 documentation
assertion after Gate 1.2 had correctly moved from CURRENT to PASS/CLOSED. The
assertion was corrected and the full suite then passed.

Accepted formal contract:

```text
LivePlatformAdapter
  resolve_creator(input)
  get_creator_profile(account)
  get_live_snapshot(account)
```

Formal live status remains exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

`resolve_creator()` returns external/provider identity only and does not invent
Stage Letter persistence ids. `AdapterRegistry` remains explicit wiring only.

Gate 1.3-1: **PASS / CLOSED**.

## 4. Gate 1.3-2 — CURRENT

Landed assets:

```text
stage_letter/infrastructure/platforms/failures.py
tests/gate1/test_provider_failure_normalization.py
docs/gate1/GATE_1_3_FAILURE_NORMALIZATION.md
```

Normalized diagnostic failure categories now cover:

```text
TIMEOUT
NETWORK
FORBIDDEN
RATE_LIMITED
AUTH_REQUIRED
CAPTCHA_REQUIRED
PARSE_ERROR
SCHEMA_DRIFT
AMBIGUOUS
NOT_FOUND
UPSTREAM_ERROR
UNKNOWN
```

These are infrastructure diagnostics, not new canonical live states.

The frozen truth rule is:

```text
provider failure / ambiguity -> UNKNOWN
```

including timeout, network errors, 401/403/404/429, captcha/auth challenges,
parse errors, schema drift, ambiguous results, and upstream failures. None may be
silently coerced to OFFLINE.

Only evidence-backed provider-specific values supplied by later concrete adapters
may map explicitly to LIVE or OFFLINE. Unrecognized/missing values remain
UNKNOWN.

Gate 1.3-2 adds eleven dedicated contracts; with the accepted 121-test baseline,
the current complete Gate 1 target is 132 tests.

## 5. Legacy treatment

The existing top-level `platform_adapters/*` package remains legacy migration
debt. Formal `stage_letter/*` does not import it.

Gate 1.3-3 and 1.3-4 will migrate provider implementations explicitly rather than
wrapping or importing the legacy package inward as an authoritative dependency.

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
Gate 1.3-1  PASS / 10 dedicated + 121 full Gate 1 evidence
Gate 1.3-2  CURRENT / failure normalization + 11 contracts landed; local evidence pending
Gate 1.3-3  NOT STARTED
Gate 1.3-4  NOT STARTED
Gate 1.3-5  NOT STARTED
Gate 1.3    CURRENT
```

## 8. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
adding provider-specific statuses to formal LiveStatus
converting failure/ambiguity to OFFLINE by default
adapter mutating canonical session/event state
adapter generating Stage Letter persistence ids
formal application importing provider/infrastructure code
formal infrastructure importing legacy platform_adapters as runtime dependency
hidden provider fallback that obscures source provenance
failure normalization inventing live start/title facts
```
