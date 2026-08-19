# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freeze:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)

## 1. Goal

Gate 1.3 introduces the formal platform-adapter boundary that converts external
provider responses into normalized Stage Letter facts without allowing provider
vocabulary or transport failures to become canonical domain truth.

Canonical direction:

```text
provider implementation
  -> LivePlatformAdapter
      -> ResolvedCreator / CreatorProfileSnapshot / LiveSnapshot
          -> application orchestration
              -> later observation/state pipeline
```

Adapters emit facts only. They do not persist canonical sessions/events or decide
notification eligibility.

## 2. Gate 1.3 slices

```text
Gate 1.3-1  Adapter Contract + Registry Freeze
Gate 1.3-2  Provider Error / Ambiguity Normalization
Gate 1.3-3  Douyin Formal Adapter Migration
Gate 1.3-4  Bilibili / Huya / Douyu Formal Adapter Migration
Gate 1.3-5  Adapter Regression / Acceptance
```

The later slice breakdown may be refined only if implementation evidence requires
it; Gate 0 semantics may not be weakened to make migration easier.

## 3. Gate 1.3-1 — CURRENT

Landed assets:

```text
stage_letter/application/platforms.py
stage_letter/infrastructure/platforms/__init__.py
stage_letter/infrastructure/platforms/registry.py
tests/gate1/test_platform_adapter_contract.py
docs/gate1/GATE_1_3_ADAPTER_CONTRACT.md
```

Formal contract:

```text
LivePlatformAdapter
  resolve_creator(input)
  get_creator_profile(account)
  get_live_snapshot(account)
```

Normalized types:

```text
ResolvedCreator
CreatorProfileSnapshot
LiveSnapshot
```

`LiveSnapshot.status` is the already-frozen formal `LiveStatus` enum and therefore
contains only:

```text
LIVE
OFFLINE
UNKNOWN
```

Provider failures or ambiguity must never be encoded as OFFLINE merely because
an adapter could not prove LIVE.

## 4. Identity rule

`resolve_creator()` returns provider identity only. It does not fabricate Stage
Letter persistence ids such as `creator_id` or `account_id`.

Internal identities remain owned by the persistence/application workflow rather
than by third-party providers.

## 5. Registry rule

The formal `AdapterRegistry` is an infrastructure-owned mapping from platform
name to an implementation of `LivePlatformAdapter`.

It provides explicit registration and lookup only. It does not:

```text
auto-import legacy platform_adapters
choose providers based on hidden fallback rules
mutate live truth
create LiveSession / LiveEvent
perform scheduling
```

## 6. Legacy treatment

The existing top-level `platform_adapters/*` package remains legacy migration
debt. Gate 1.3-1 does not import it into the formal runtime.

Provider-specific migration will be explicit in later Gate 1.3 slices after the
normalized contract and error rules are accepted.

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
Gate 1.3-1  CURRENT / contract + registry + tests landed; local evidence pending
Gate 1.3-2  NOT STARTED
Gate 1.3-3  NOT STARTED
Gate 1.3-4  NOT STARTED
Gate 1.3-5  NOT STARTED
Gate 1.3    CURRENT
```
