# Gate 1.2 — Repository / Service Boundaries

Status: **PASS / CLOSED**

Entry authority: Gate 1.1 PASS.

Primary freezes:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)
- [`GATE_1_2_REPOSITORIES.md`](./GATE_1_2_REPOSITORIES.md)
- [`GATE_1_2_UOW.md`](./GATE_1_2_UOW.md)
- [`GATE_1_2_SERVICES.md`](./GATE_1_2_SERVICES.md)
- [`GATE_1_2_COMPOSITION.md`](./GATE_1_2_COMPOSITION.md)
- [`GATE_1_2_ACCEPTANCE.md`](./GATE_1_2_ACCEPTANCE.md)

## 1. Goal

Gate 1.2 turns the Gate 1.1 formal domain/persistence contracts into an explicit
runtime architecture where business semantics flow through application ports and
services rather than legacy API/worker modules or direct ORM access.

```text
api/workers composition roots
        -> infrastructure implementations
        -> application ports/services
        -> domain
```

Infrastructure may depend on application ports and domain. Application may not
depend on infrastructure. Domain depends only on itself/stdlib.

## 2. Final slice status

```text
Gate 1.2-1  PASS / boundary contracts
Gate 1.2-2  PASS / repositories + PostgreSQL + migration evidence
Gate 1.2-3  PASS / 9 UoW tests + 88 full tests + PostgreSQL probe
Gate 1.2-4  PASS / 10 service tests + 98 full tests
Gate 1.2-5  PASS / 7 composition-root tests + 105 full tests
Gate 1.2-6  PASS / 6 acceptance tests + 111 full tests + regression probe
```

The accepted architecture keeps domain truth inward, repositories as persistence
translators, UnitOfWork as transaction owner, application services as use-case
orchestrators, and API/workers as outer composition roots.

## 3. Final acceptance evidence

User-local final acceptance:

```text
Gate 1.2 acceptance contracts: 6 / 6 PASS
Complete Gate 1 suite:         111 / 111 PASS
Gate 1.2 regression probe:     PASS
```

The deterministic probe also preserves accepted Gate 0B/0C/0D/0E oracle
minimums, Alembic head `c91e8d2f4a10`, and UTF-8 offline SQL compilation.

Gate 0A remains **DEGRADED** with its known deferred lifecycle evidence gap.
No provider resend or fabricated lifecycle evidence was used to close Gate 1.2.

## 4. Legacy debt remains explicit

Inherited modules such as `api/routers/*`, `api/services/*`,
`workers/probe/worker.py`, `workers/notify/*`, `core/*`, and
`platform_adapters/*` remain staged migration debt. Gate 1.2 does not falsely
claim they are already semantically replaced.

The enforced boundary is:

```text
formal stage_letter runtime never imports those legacy outer packages
new orchestration enters through formal services/ports
later gates own provider/scheduler/state/notification/API semantic cutover
```

## 5. Preserved inherited status

```text
Gate 0A    DEGRADED / known deferred lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E    PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   CURRENT
```

Gate 1.2 does not alter Gate 0A, rewrite accepted historical migrations, or
fabricate historical truth.

## 6. Handoff to Gate 1.3

Gate 1.3 owns the formal Platform Adapter Framework. It must introduce an
infrastructure-independent adapter contract and normalized snapshots before any
legacy provider implementation is migrated inward.

Gate 1.3 must preserve:

```text
LIVE / OFFLINE / UNKNOWN only at the formal live-status boundary
UNKNOWN != OFFLINE
adapters emit normalized facts only
adapters do not mutate canonical LiveSession/LiveEvent truth
provider/network errors normalize conservatively rather than invent OFFLINE
legacy platform_adapters package remains quarantine debt until explicitly migrated
```
