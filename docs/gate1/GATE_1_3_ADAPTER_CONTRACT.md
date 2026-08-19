# Gate 1.3-1 — Adapter Contract + Registry Freeze

Status: **CURRENT / CODE + CONTRACTS LANDED / LOCAL EVIDENCE PENDING**

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

This preserves the Gate 1 architecture freeze semantically:

```text
resolveCreator
getCreatorProfile
getLiveSnapshot
```

with Python naming conventions only.

## 3. Normalized facts

### ResolvedCreator

Carries external/provider identity discovered from user input:

```text
platform
platform_user_id
display_name?
room_id?
canonical_url?
```

It deliberately has no Stage Letter `creator_id` or `account_id`. Adapters must
not invent persistence identities.

### CreatorProfileSnapshot

Carries provider profile facts observed at a point in time:

```text
platform
platform_user_id
observed_at
display_name?
avatar_url?
bio?
```

### LiveSnapshot

Carries provider live-state facts:

```text
platform
platform_user_id
status
observed_at
source
source_started_at?
room_id?
canonical_url?
title?
```

The status type is `stage_letter.domain.live.LiveStatus`, exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

## 4. Conservative truth rule

The adapter boundary must preserve:

```text
UNKNOWN != OFFLINE
```

Examples that cannot be silently coerced to OFFLINE include:

```text
timeout
network failure
403 / 429
provider auth or captcha challenge
parse failure
missing required status field
provider schema drift
conflicting/ambiguous provider response
```

Gate 1.3-2 will formalize the provider error/ambiguity mapping. Gate 1.3-1 only
freezes the output contract so no later implementation can reintroduce legacy
7-state/provider-specific truth inward.

## 5. Adapter responsibility

Allowed:

```text
provider request/response translation
external identity resolution
profile normalization
live snapshot normalization
provider-specific parsing inside infrastructure
```

Forbidden:

```text
persisting LiveObservation directly
opening/closing LiveSession
creating LiveEvent
UNKNOWN -> OFFLINE coercion
notification eligibility
notification send
scheduler ownership
committing application transactions
fabricating internal persistence ids
```

## 6. Registry

Formal registry:

```text
stage_letter/infrastructure/platforms/registry.py
```

`AdapterRegistry` owns only explicit platform -> adapter wiring.

Rules:

```text
platform key must be non-empty
duplicate registration rejected
non-adapter registration rejected
missing adapter lookup raises AdapterNotFoundError
registry has no legacy/provider auto-imports
registry has no domain transition logic
```

The registry intentionally does not silently lowercase, alias, or fallback across
platform names; those policies must be explicit and evidence-backed if introduced
later.

## 7. Dependency boundary

`stage_letter/application/platforms.py` may import only standard library and
formal domain vocabulary required by the contract.

It must not import:

```text
stage_letter.infrastructure
api / workers
core
platform_adapters
experiments
SQLAlchemy / FastAPI
requests / httpx / provider SDKs
```

Concrete adapters belong in `stage_letter/infrastructure/platforms/*` and may
implement provider-specific transport there without leaking provider vocabulary
inward.

## 8. Contract tests

Landed:

```text
tests/gate1/test_platform_adapter_contract.py
```

The ten checks verify:

```text
formal three-state LiveStatus remains exact
ResolvedCreator has provider identity but no internal persistence ids
UNKNOWN survives the normalized snapshot unchanged
LivePlatformAdapter is a structural runtime protocol
registry register/get/contains/platforms behavior
duplicate registration rejection
non-adapter rejection
missing adapter lookup is explicit
application adapter contract has no infrastructure/provider imports
registry has no legacy adapter or session/event truth logic
```

## 9. Acceptance

Gate 1.3-1 PASS requires:

```text
A. Gate 1.2 PASS / CLOSED                              PASS
B. infrastructure-free adapter contract                CODE LANDED
C. normalized snapshot DTOs                            CODE LANDED
D. explicit formal adapter registry                    CODE LANDED
E. UNKNOWN != OFFLINE preserved                        CONTRACT LANDED
F. no internal id fabrication by resolve_creator       CONTRACT LANDED
G. legacy platform_adapters not imported inward        CONTRACT LANDED
H. dedicated adapter contract tests pass               PENDING / 10
I. complete Gate 1 suite remains green                 PENDING
```

Gate 1.3-1 remains **CURRENT** until H-I pass.

## 10. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
adding provider-specific statuses to formal LiveStatus
converting ambiguity/failure to OFFLINE by default
adapter mutating canonical session/event state
adapter generating Stage Letter persistence ids
formal application importing provider/infrastructure code
formal infrastructure importing legacy platform_adapters directly as runtime dependency
hidden registry fallback that obscures which source produced the fact
```
