# Gate 1.3-1 — Adapter Contract + Registry Freeze

Status: **PASS / CLOSED**

Entry authority: Gate 1.2 PASS / CLOSED.

## 1. Purpose

Gate 1.3-1 freezes the provider-facing contract before any legacy platform
implementation is migrated into `stage_letter/infrastructure`.

The contract is application-owned and infrastructure-free so application use
cases may depend on it without importing concrete provider code.

## 2. Formal interface

Python contract:

```text
LivePlatformAdapter
  async resolve_creator(input: str) -> ResolvedCreator
  async get_creator_profile(account: PlatformAccount) -> CreatorProfileSnapshot
  async get_live_snapshot(account: PlatformAccount) -> LiveSnapshot
```

Normalized facts remain:

```text
ResolvedCreator
CreatorProfileSnapshot
LiveSnapshot
```

`LiveSnapshot.status` is exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

## 3. Accepted invariants

```text
UNKNOWN != OFFLINE
resolve_creator returns provider identity only
adapter never fabricates Stage Letter creator_id/account_id
adapter does not persist canonical LiveSession/LiveEvent truth
adapter does not own scheduler or notification eligibility
formal application contract imports no provider/infrastructure implementation
formal registry does not auto-import legacy platform_adapters
```

Provider failure/ambiguity normalization is intentionally delegated to Gate
1.3-2 rather than encoded as new formal live states.

## 4. Registry

`stage_letter/infrastructure/platforms/registry.py` owns explicit
`platform -> LivePlatformAdapter` wiring only.

Accepted behavior:

```text
non-empty explicit platform key
duplicate registration rejected
non-adapter registration rejected
missing lookup raises AdapterNotFoundError
no hidden alias/lowercase/fallback policy
no state/session/event semantics
```

## 5. Accepted local evidence

The first 121-test full-suite run showed all ten adapter contract tests green, but
one stale historical Gate 1.2 document assertion failed after Gate 1.2 had
correctly advanced from CURRENT to PASS/CLOSED. That stale assertion was fixed to
assert the final closed Gate 1.2 state.

The corrected local evidence is:

```text
Gate 1.2 historical acceptance contracts: 6 / 6 PASS
Complete Gate 1 suite:                  121 / 121 PASS
Gate 1.3-1 adapter contracts:           10 / 10 PASS (included in full suite)
```

The transient stale-document failure was therefore not an adapter defect.

## 6. Acceptance result

```text
A. Gate 1.2 PASS / CLOSED                              PASS
B. infrastructure-free adapter contract                PASS
C. normalized snapshot DTOs                            PASS
D. explicit formal adapter registry                    PASS
E. UNKNOWN != OFFLINE preserved                        PASS
F. no internal id fabrication by resolve_creator       PASS
G. legacy platform_adapters not imported inward        PASS
H. dedicated adapter contract tests                    PASS / 10
I. complete Gate 1 suite                               PASS / 121
```

Gate 1.3-1: **PASS / CLOSED**.

Next: Gate 1.3-2 — Provider Error / Ambiguity Normalization.

## 7. Preserved stop rules

The accepted contract must not later be weakened by:

```text
provider-specific statuses added to formal LiveStatus
ambiguity/failure converted to OFFLINE by default
adapter mutating canonical session/event truth
adapter generating internal persistence ids
formal application importing provider/infrastructure code
formal infrastructure importing legacy platform_adapters as runtime dependency
hidden registry fallback that obscures source provenance
```
