# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 PASS / 1.2-2 PASS / 1.2-3 PASS / 1.2-4 PASS / 1.2-5 PASS / 1.2-6 CURRENT**

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

## 2. Gate 1.2 slices

```text
Gate 1.2-1  Boundary Freeze + AST Contracts
Gate 1.2-2  SQLAlchemy Repository Implementations
Gate 1.2-3  SQLAlchemy UnitOfWork + transaction semantics
Gate 1.2-4  Application Services
Gate 1.2-5  API/Worker Composition Roots + legacy cutover
Gate 1.2-6  Boundary Regression / acceptance
```

## 3. Accepted slices

```text
Gate 1.2-1  PASS / boundary contracts
Gate 1.2-2  PASS / repositories + PostgreSQL + migration evidence
Gate 1.2-3  PASS / 9 UoW tests + 88 full tests + PostgreSQL probe
Gate 1.2-4  PASS / 10 service tests + 98 full tests
Gate 1.2-5  PASS / 7 composition-root tests + 105 full tests
```

The accepted slices preserve the intended separation: domain truth is formal,
repositories translate persistence only, UnitOfWork owns transactions,
application services own use-case orchestration, and API/workers are outer
composition roots.

## 4. Gate 1.2-6 — CURRENT

Final regression assets now landed:

```text
tests/gate1/test_gate12_acceptance.py
scripts/gate12_regression_probe.py
docs/gate1/GATE_1_2_ACCEPTANCE.md
```

The final acceptance contracts add six checks. With the accepted 105-test Gate 1
baseline, the full formal suite should therefore contain 111 tests.

The deterministic final probe verifies:

```text
Gate 0B oracle >= 37
Gate 0C oracle >= 65
Gate 0D oracle >= 54
Gate 0E oracle >= 15
Gate 1 formal contracts >= 111
Alembic head == c91e8d2f4a10
UTF-8 offline SQL compilation PASS
```

It does not repeat real provider/network calls or WeChat sends and does not
fabricate the deferred Gate 0A lifecycle evidence.

Gate 1.2-6 remains CURRENT until the dedicated six acceptance contracts, the
111-test Gate 1 suite, and the deterministic regression probe all pass locally.

## 5. Legacy debt remains explicit

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

## 6. Preserved inherited status

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

Gate 1.2 does not alter Gate 0A, rewrite accepted historical migrations, or
fabricate historical truth.

## 7. Stop rules

Stop with FAIL/BLOCKED if acceptance pressure requires any of:

```text
domain importing ORM/framework/provider code
application importing concrete infrastructure
formal stage_letter runtime importing api/workers/core/platform_adapters/experiments
API/worker composition root becoming a domain-rule owner
repository-owned commit or unrelated sessions inside one UnitOfWork
provider/network calls inside application DB transactions
implicit/lossy identity conversion or fabricated ids
Follow and NotificationPreference collapsing
raw observation being treated as canonical composed state
UNKNOWN -> OFFLINE semantic drift
lowering accepted regression minimums to hide failures
fabricating Gate 0A lifecycle evidence
```

## 8. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS
Gate 1.2-2  PASS
Gate 1.2-3  PASS
Gate 1.2-4  PASS
Gate 1.2-5  PASS / 7 dedicated + 105 full Gate 1 tests
Gate 1.2-6  CURRENT / final acceptance assets landed; local evidence pending
Gate 1.2    CURRENT
```
