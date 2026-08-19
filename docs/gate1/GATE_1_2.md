# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 PASS / 1.2-2 CURRENT**

Entry authority: Gate 1.1 PASS.

Primary freezes:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)
- [`GATE_1_2_REPOSITORIES.md`](./GATE_1_2_REPOSITORIES.md)

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

`stage_letter/application/ports.py` defines the repository and UnitOfWork ports
accepted in Gate 1.1.

Inherited pre-formal implementation still exists under top-level legacy paths,
including `api/services/*`, `workers/*`, `core/*`, and `platform_adapters/*`.
Those modules remain migration debt and are not allowed to become dependencies
of formal `stage_letter/*` runtime code.

## 3. Gate 1.2 slices

```text
Gate 1.2-1  Boundary Freeze + AST Contracts
Gate 1.2-2  SQLAlchemy Repository Implementations
Gate 1.2-3  SQLAlchemy UnitOfWork + transaction semantics
Gate 1.2-4  Application Services
Gate 1.2-5  API/Worker Composition Roots + legacy cutover
Gate 1.2-6  Boundary Regression / acceptance
```

## 4. Gate 1.2-1 — PASS

Landed assets:

```text
docs/gate1/GATE_1_2_BOUNDARY_FREEZE.md
tests/gate1/test_service_boundaries.py
```

Accepted user-local evidence:

```text
Ran 62 tests in 0.189s
OK
```

The full suite includes the seven AST/service-boundary contracts and preserves
all earlier Gate 1 tests. The dependency freeze is therefore accepted.

Gate 1.2-1: **PASS**.

## 5. Gate 1.2-2 — SQLAlchemy Repository Implementations — CURRENT

Target package:

```text
stage_letter/infrastructure/db/repositories/
  creator.py
  follow.py
  live.py
  notification.py
```

Implementations must satisfy the Gate 1.1 ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
```

Repository responsibilities are limited to persistence translation and query /
write behavior. They must not commit independently, own business transitions,
call providers, or reinterpret canonical truth.

The first repository contract has landed:

```text
stage_letter/infrastructure/db/repositories/identity.py
tests/gate1/test_repository_identity.py
docs/gate1/GATE_1_2_REPOSITORIES.md
```

It makes the existing Gate 1 schema/domain identity boundary explicit: domain
ids backed only by PostgreSQL BIGINT keys use canonical positive decimal strings;
formal observation/event evidence ids remain native strings. Lossy or implicit
conversion is forbidden.

Repository inspection also exposed transitional legacy NOT NULL bridge columns
such as `platform_accounts.anchor_id` and
`notification_deliveries.notification_job_id`. Gate 1.2-2 will not fabricate
legacy anchors/jobs merely to satisfy those columns. A forward-only compatible
write-bridge resolution must be proven before repository write acceptance.

Current local evidence for the new identity tests is pending.

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

Gate 1.2 does not alter the Gate 0A status and does not rewrite historical
migrations or fabricate historical truth.

## 7. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires any of:

```text
domain importing ORM/framework/provider code
application importing infrastructure implementations
formal stage_letter runtime importing experiments/core/legacy runtime packages
API/worker handler becoming canonical business-rule owner
direct ORM mutations that bypass an existing application service contract
repository method committing independently inside UnitOfWork flow
provider/network calls hidden inside repository transactions
implicit or lossy identity conversion
fabricated persistence IDs or historical identities
fake legacy anchor/job bridge rows
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```

## 8. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS / 62-test full suite incl. 7 boundary contracts
Gate 1.2-2  CURRENT / identity + bridge contract; local evidence pending
Gate 1.2-3  NOT STARTED
Gate 1.2-4  NOT STARTED
Gate 1.2-5  NOT STARTED
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
