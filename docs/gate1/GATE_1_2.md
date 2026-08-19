# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 PASS / 1.2-2 PASS / 1.2-3 PASS / 1.2-4 PASS / 1.2-5 CURRENT**

Entry authority: Gate 1.1 PASS.

Primary freezes:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)
- [`GATE_1_2_REPOSITORIES.md`](./GATE_1_2_REPOSITORIES.md)
- [`GATE_1_2_UOW.md`](./GATE_1_2_UOW.md)
- [`GATE_1_2_SERVICES.md`](./GATE_1_2_SERVICES.md)
- [`GATE_1_2_COMPOSITION.md`](./GATE_1_2_COMPOSITION.md)

## 1. Goal

Gate 1.2 turns the formal Gate 1.1 domain and PostgreSQL schema into an explicit
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
```

Gate 1.2-4 preserves the intended separation: Creator, Follow, Notification
Preference, and raw LiveObservation orchestration are formal application
services, while provider/state/session/event/notification-runtime semantics stay
in their later gates.

## 4. Gate 1.2-5 — CURRENT

Landed assets:

```text
api/composition.py
workers/composition.py
tests/gate1/test_composition_roots.py
docs/gate1/GATE_1_2_COMPOSITION.md
```

`api/main.py` now exposes the formal application-service bundle at:

```text
app.state.stage_letter_services
```

The new composition roots wire application services to `SQLAlchemyUnitOfWork`
using a supplied session factory. They do not import domain rules, provider
adapters, experiments, or legacy core behavior.

Legacy modules such as `api/routers/subscriptions.py` and
`workers/probe/worker.py` remain operational debt during staged migration. They
are not considered formally cut over merely because the new composition seam
exists. Their semantic replacement belongs to Gates 1.3-1.7 as appropriate.

Gate 1.2-5 remains CURRENT until its dedicated composition-root tests and the
full Gate 1 suite pass locally.

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

Gate 1.2 does not alter Gate 0A, rewrite historical migrations, or fabricate
historical truth.

## 6. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires any of:

```text
domain importing ORM/framework/provider code
application importing concrete infrastructure
formal stage_letter runtime importing api/workers/core/platform_adapters/experiments
API/worker composition root becoming a domain-rule owner
repository-owned commit or multiple unrelated UoW sessions
provider/network calls inside application DB transactions
implicit/lossy identity conversion or fabricated ids
Follow and NotificationPreference collapsing
raw observation being treated as canonical composed state
UNKNOWN -> OFFLINE semantic drift
premature copying of legacy probe/state logic into formal services
```

## 7. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS
Gate 1.2-2  PASS
Gate 1.2-3  PASS
Gate 1.2-4  PASS / 10 dedicated + 98 full Gate 1 tests
Gate 1.2-5  CURRENT / formal API+worker roots landed; local evidence pending
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
