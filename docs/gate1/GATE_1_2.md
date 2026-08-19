# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 BOUNDARY FREEZE CURRENT**

Entry authority: Gate 1.1 PASS.

Primary freeze:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)

## 1. Goal

Gate 1.2 turns the formal Gate 1.1 domain and PostgreSQL schema into an explicit
runtime architecture where business semantics flow through application ports and
services rather than legacy API/worker modules or direct ORM access.

Canonical dependency direction:

```text
api/workers composition roots
        -> infrastructure implementations
        -> application ports/services
        -> domain
```

Infrastructure may depend on application ports and domain. Application may not
depend on infrastructure. Domain depends only inward on itself/stdlib.

## 2. Current repository facts

The formal runtime currently exists under:

```text
stage_letter/domain/
stage_letter/application/
stage_letter/infrastructure/db/
```

`stage_letter/application/ports.py` already defines the repository and UnitOfWork
ports accepted in Gate 1.1.

Inherited pre-formal implementation still exists under top-level legacy paths,
including `api/services/*`, `workers/*`, `core/*`, and `platform_adapters/*`.
Those modules are migration debt and are not allowed to become dependencies of
formal `stage_letter/*` runtime code.

## 3. Gate 1.2 slices

```text
Gate 1.2-1  Boundary Freeze + AST Contracts
Gate 1.2-2  SQLAlchemy Repository Implementations
Gate 1.2-3  SQLAlchemy UnitOfWork + transaction semantics
Gate 1.2-4  Application Services
Gate 1.2-5  API/Worker Composition Roots + legacy cutover
Gate 1.2-6  Boundary Regression / acceptance
```

## 4. Gate 1.2-1 — CURRENT

Landed assets:

```text
docs/gate1/GATE_1_2_BOUNDARY_FREEZE.md
tests/gate1/test_service_boundaries.py
```

The freeze establishes:

```text
domain: stdlib/domain only
application: domain + application ports/services only
infrastructure: may implement ports; cannot depend on API/workers/legacy runtime
api/workers target: composition roots only
experiments: evidence/oracle only, never formal runtime dependency
```

Known legacy API/worker service code is explicitly quarantined instead of being
silently treated as compliant.

Gate 1.2-1 requires local contract evidence before PASS.

## 5. Preserved inherited status

```text
Gate 0A    DEGRADED / known deferred lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    PASS
Gate 0E    PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   CURRENT
```

Gate 1.2 does not alter the Gate 0A status and does not rewrite historical
migrations or fabricate historical truth.

## 6. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires any of:

```text
domain importing ORM/framework/provider code
application importing infrastructure implementations
formal stage_letter runtime importing experiments/core/legacy runtime packages
API/worker handler becoming canonical business-rule owner
direct ORM mutations that bypass an existing application service contract
repository method committing independently inside UnitOfWork flow
provider/network calls hidden inside repository transactions
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```

## 7. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  CURRENT / freeze + tests landed; local evidence pending
Gate 1.2-2  NOT STARTED
Gate 1.2-3  NOT STARTED
Gate 1.2-4  NOT STARTED
Gate 1.2-5  NOT STARTED
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
