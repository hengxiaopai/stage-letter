# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 PASS / 1.2-2 PASS / 1.2-3 CURRENT**

Entry authority: Gate 1.1 PASS.

Primary freezes:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)
- [`GATE_1_2_REPOSITORIES.md`](./GATE_1_2_REPOSITORIES.md)
- [`GATE_1_2_UOW.md`](./GATE_1_2_UOW.md)

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

## 2. Gate 1.2 slices

```text
Gate 1.2-1  Boundary Freeze + AST Contracts
Gate 1.2-2  SQLAlchemy Repository Implementations
Gate 1.2-3  SQLAlchemy UnitOfWork + transaction semantics
Gate 1.2-4  Application Services
Gate 1.2-5  API/Worker Composition Roots + legacy cutover
Gate 1.2-6  Boundary Regression / acceptance
```

## 3. Gate 1.2-1 — PASS

Accepted user-local evidence:

```text
Ran 62 tests in 0.189s
OK
```

The full suite includes the seven AST/service-boundary contracts and preserves
all earlier Gate 1 tests.

## 4. Gate 1.2-2 — PASS

Accepted identity evidence:

```text
Repository identity tests: 7 / 7 PASS
Full Gate 1 suite:          69 / 69 PASS
```

Accepted real PostgreSQL repository evidence:

```text
[gate12] seeded at Gate 1.1 head -> b63e4f9a1c20
[gate12] bridge migration PASS -> c91e8d2f4a10
PASS: Gate 1.2-2 SQLAlchemy repositories + legacy write bridge
[cleanup] dropped stageletter_gate12_repo
```

Accepted final static evidence:

```text
Ran 78 tests in 0.444s
OK

c91e8d2f4a10 (head)

PASS: Gate 1.2 offline SQL compilation
```

Gate 1.2-2 therefore closes PASS. The four formal repositories now operate
against PostgreSQL without fabricating legacy bridge facts, and repository
methods do not own transaction commits.

## 5. Gate 1.2-3 — SQLAlchemy UnitOfWork — CURRENT

Landed assets:

```text
stage_letter/infrastructure/db/uow.py
tests/gate1/test_uow_contract.py
scripts/gate12_uow_probe.py
docs/gate1/GATE_1_2_UOW.md
```

The concrete UnitOfWork creates one AsyncSession per entered context and binds
all four repositories to that exact session. Commit is explicit; normal exit
without commit rolls back; exceptional exit before commit rolls back and
propagates; the session always closes.

The PostgreSQL probe will verify multi-repository atomic commit and rollback in
an isolated `stageletter_gate12_uow` database.

Gate 1.2-3 remains CURRENT until its local contract suite, full Gate 1 suite, and
real PostgreSQL transaction probe pass.

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

Gate 1.2 does not alter Gate 0A, rewrite historical migrations, or fabricate
historical truth.

## 7. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires any of:

```text
domain importing ORM/framework/provider code
application importing infrastructure implementations
formal stage_letter runtime importing experiments/core/legacy runtime packages
API/worker handler becoming canonical business-rule owner
direct ORM mutations that bypass an existing application service contract
repository method committing independently inside UnitOfWork flow
multiple unrelated DB sessions inside one UnitOfWork
implicit auto-commit on successful context exit
provider/network calls hidden inside repository transactions
implicit or lossy identity conversion
fabricated persistence IDs or historical identities
fake legacy anchor/job bridge rows
session-based notification idempotency
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```

## 8. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS
Gate 1.2-2  PASS / 78-test + PostgreSQL + head + offline SQL evidence
Gate 1.2-3  CURRENT / UnitOfWork code + contracts + DB probe landed; local evidence pending
Gate 1.2-4  NOT STARTED
Gate 1.2-5  NOT STARTED
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
