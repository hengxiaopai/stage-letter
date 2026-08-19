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

Gate 1.2-1: **PASS**.

## 4. Gate 1.2-2 — CURRENT

Identity contract evidence:

```text
Repository identity tests: 7 / 7 PASS
Full Gate 1 suite:          69 / 69 PASS
```

Implementation assets landed:

```text
migrations/versions/c91e8d2f4a10_gate12_relax_legacy_write_bridges.py

stage_letter/infrastructure/db/repositories/
  common.py
  identity.py
  creator.py
  follow.py
  live.py
  notification.py

tests/gate1/test_repository_implementations.py
scripts/gate12_repository_probe.py
```

The compatibility revision follows `b63e4f9a1c20` and lets new formal rows leave
obsolete legacy bridge fields NULL instead of fabricating anchors, notification
jobs, stale status, confidence, or provenance facts. It also removes the old
session-keyed delivery uniqueness because canonical delivery idempotency is
already event-keyed.

The four repository implementations satisfy the formal ports structurally and
do not own transaction commits. The LiveRepository observation lookup is aligned
with the already accepted durable identity:

```text
(account_id, source, observation_id)
```

Real PostgreSQL repository evidence now passes:

```text
[gate12] seeded at Gate 1.1 head -> b63e4f9a1c20
[gate12] bridge migration PASS -> c91e8d2f4a10
PASS: Gate 1.2-2 SQLAlchemy repositories + legacy write bridge
[cleanup] dropped stageletter_gate12_repo
```

This proves the bridge migration and four repository implementations work
against isolated PostgreSQL without fabricating legacy bridge facts. The first
probe attempt was blocked only by direct-script Python import bootstrap and was
fixed before the successful run.

Gate 1.2-2 is not closed yet. Remaining acceptance evidence is the post-change
full Gate 1 suite/boundary contracts, the Alembic head check, and UTF-8 offline
SQL compilation through `c91e8d2f4a10`.

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
implicit or lossy identity conversion
fabricated persistence IDs or historical identities
fake legacy anchor/job bridge rows
session-based notification idempotency
UNKNOWN -> OFFLINE or other Gate 0 semantic drift
```

## 7. Current progression

```text
Gate 1.1    PASS
Gate 1.2-1  PASS / 62-test full suite incl. 7 boundary contracts
Gate 1.2-2  CURRENT / PostgreSQL probe PASS; static acceptance pending
Gate 1.2-3  NOT STARTED
Gate 1.2-4  NOT STARTED
Gate 1.2-5  NOT STARTED
Gate 1.2-6  NOT STARTED
Gate 1.2    CURRENT
```
