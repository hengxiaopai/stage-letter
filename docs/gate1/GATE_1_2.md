# Gate 1.2 — Repository / Service Boundaries

Status: **CURRENT / 1.2-1 PASS / 1.2-2 PASS / 1.2-3 PASS / 1.2-4 CURRENT**

Entry authority: Gate 1.1 PASS.

Primary freezes:

- [`GATE_1_2_BOUNDARY_FREEZE.md`](./GATE_1_2_BOUNDARY_FREEZE.md)
- [`GATE_1_2_REPOSITORIES.md`](./GATE_1_2_REPOSITORIES.md)
- [`GATE_1_2_UOW.md`](./GATE_1_2_UOW.md)
- [`GATE_1_2_SERVICES.md`](./GATE_1_2_SERVICES.md)

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

Accepted evidence includes:

```text
Repository identity tests: 7 / 7 PASS
Full Gate 1 suite:          69 / 69 PASS
PostgreSQL repository probe PASS
Full post-implementation suite: 78 / 78 PASS
Alembic head: c91e8d2f4a10
Offline SQL compilation PASS
```

The four formal repositories operate against PostgreSQL without fabricating
legacy bridge facts, and repository methods do not own transaction commits.

## 5. Gate 1.2-3 — PASS

Accepted user-local evidence after correcting the mixed ORM/Core flush-order
defect:

```text
Dedicated UnitOfWork contracts: 9 tests PASS
Full Gate 1 suite:              88 tests PASS
PostgreSQL UnitOfWork probe:    PASS
```

The real probe proves one shared AsyncSession across all four repositories,
explicit atomic commit, normal uncommitted rollback, exceptional rollback +
propagation, and safe FK ordering through explicit flush without early commit.

Gate 1.2-3 is therefore **PASS / CLOSED**.

## 6. Gate 1.2-4 — Application Services — CURRENT

Landed assets:

```text
stage_letter/application/errors.py
stage_letter/application/services/
  __init__.py
  creator.py
  follow.py
  live.py

tests/gate1/test_application_services.py
docs/gate1/GATE_1_2_SERVICES.md
```

Initial formal use-cases now cover:

```text
CreatorApplicationService
  save already-resolved Creator/Profile/PlatformAccount as one UoW
  cross-entity creator identity checked before persistence

FollowApplicationService
  follow account using persisted creator identity
  unfollow relation
  update NotificationPreference separately

LiveObservationApplicationService
  persist normalized LiveObservation and commit
  no transition/session/event interpretation
```

Gate 1.2-4 deliberately does not move Gate 0B/0C state semantics, provider
composition, scheduler behavior, or notification eligibility into the service
layer. Those remain later-gate responsibilities.

Current acceptance evidence for the new application-service contracts is pending.

## 7. Preserved inherited status

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

## 8. Stop rules

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
provider/network calls hidden inside DB transactions
implicit or lossy identity conversion
fabricated persistence IDs or historical identities
Follow and NotificationPreference collapsing again
raw observation being treated as canonical composed status
premature UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```

## 9. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS
Gate 1.2-2  PASS
Gate 1.2-3  PASS / 9-test + 88-test + PostgreSQL evidence
Gate 1.2-4  CURRENT / service boundary + initial use-cases landed; local evidence pending
Gate 1.2-5  NOT STARTED
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
