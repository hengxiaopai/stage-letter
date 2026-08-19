# Gate 1.2-1 — Repository / Service Boundary Freeze

Status: **CURRENT / CODE + CONTRACT TESTS LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.1 PASS.

## 1. Purpose

Gate 1.2 turns the Gate 1.1 domain/persistence contracts into an enforceable
runtime dependency graph before repository implementations, application
services, adapters, workers, or API composition are expanded.

The target architecture is:

```text
api / workers composition roots
          |
          v
stage_letter.infrastructure  ---> stage_letter.application
          |                            |
          +----------------------------+
                         |
                         v
                 stage_letter.domain
```

Dependency arrows point toward code that may be imported.

## 2. Frozen dependency rules

### Domain

`stage_letter/domain/*` is the innermost layer.

Allowed:

```text
Python standard library
other stage_letter.domain modules
```

Forbidden:

```text
stage_letter.application
stage_letter.infrastructure
api
workers
core
platform_adapters
experiments
SQLAlchemy / Alembic / asyncpg
FastAPI
Redis / Dramatiq
provider/network SDKs
```

Domain owns business vocabulary and invariants only.

### Application

`stage_letter/application/*` owns use-case orchestration and ports.

Allowed:

```text
Python standard library
stage_letter.domain
stage_letter.application ports/services
```

Forbidden:

```text
stage_letter.infrastructure
api
workers
core
platform_adapters
experiments
SQLAlchemy / Alembic / asyncpg
FastAPI
Redis / Dramatiq
provider/network SDKs
```

Application services may depend on abstract ports, never concrete repository,
queue, provider, HTTP, or ORM implementations.

### Infrastructure

`stage_letter/infrastructure/*` implements application ports and provider/network
boundaries.

Allowed:

```text
stage_letter.application ports
stage_letter.domain
SQLAlchemy / asyncpg / Redis / Dramatiq / HTTP/provider libraries
```

Forbidden:

```text
api
workers
core
platform_adapters legacy package
experiments
```

Infrastructure may translate persistence/provider records into formal domain
objects, but it must not redefine domain truth.

### API and workers

The target role for top-level `api/` and `workers/` is composition only:

```text
construct infrastructure implementations
construct application services
bind HTTP routes / worker handlers
translate transport input/output
start/stop process resources
```

They must not become the canonical home of domain rules, repository semantics,
state transitions, notification eligibility, or provider truth normalization.

## 3. Repository implementation freeze

Formal repository implementations will live under:

```text
stage_letter/infrastructure/db/repositories/
```

They implement the Gate 1.1 application ports:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
```

Rules:

```text
repository methods translate ORM rows <-> formal domain objects
repository methods do not decide business transitions
repository methods do not call external providers
repository methods do not commit independently when used through UnitOfWork
logical idempotency remains enforced by DB + repository contract
```

## 4. UnitOfWork freeze

Concrete SQLAlchemy UnitOfWork will live at:

```text
stage_letter/infrastructure/db/uow.py
```

It owns one application transaction boundary and implements the existing
`application.ports.UnitOfWork` protocol.

Required semantics:

```text
one async transaction scope
repositories share the same session/transaction
commit is explicit
rollback is explicit
exceptional exit rolls back
observation/state/session/event persistence can be atomic
no external provider call occurs inside a DB transaction merely for convenience
```

Gate 0B restart/atomicity semantics remain the oracle for later state-service
integration.

## 5. Application service freeze

Formal services belong under `stage_letter/application/` rather than
`api/services/` or `workers/*`.

Target service modules from the Gate 1.0 architecture freeze remain:

```text
creator_service.py
follow_service.py
live_observation_service.py
live_state_service.py
notification_service.py
```

Services orchestrate domain + ports. They must not import SQLAlchemy, FastAPI,
Redis, Dramatiq, requests/httpx, provider SDKs, or legacy runtime modules.

## 6. Composition-root freeze

Later Gate 1.2 work will cut formal process entrypoints over so that API and
workers wire dependencies rather than owning them.

Target flow:

```text
API/worker handler
 -> application service
 -> UnitOfWork / port
 -> infrastructure implementation
 -> domain result
```

No handler may directly mutate ORM state to bypass an application service once
its formal use case exists.

## 7. Legacy boundary debt — quarantined, not silently accepted

Current repository inspection found pre-formal runtime code still present in:

```text
api/services/*
workers/probe/worker.py
workers/notify/in_app.py
workers/notify/wechat.py
core/*
platform_adapters/*
```

This is inherited legacy implementation debt, not the Gate 1 target boundary.
It is preserved during migration to avoid destructive rewrites.

Quarantine rules:

```text
stage_letter/* MUST NOT import these legacy modules
no new formal domain/service rule may be added to these legacy locations
later Gate 1.2 slices migrate/cut over behavior explicitly
legacy code is not evidence that the formal boundary is already complete
```

The presence of legacy `api/services/*` and worker implementation files therefore
prevents claiming full Gate 1.2 PASS at this stage, but it does not block the
boundary freeze itself if the formal package remains isolated.

## 8. Boundary contract tests

`tests/gate1/test_service_boundaries.py` performs AST-based import checks. It
ignores comments/docstrings and verifies the actual formal import graph.

The tests cover:

```text
domain inward-only imports
application independence from infrastructure/frameworks
infrastructure independence from API/workers/legacy runtime
formal stage_letter runtime independence from experiments/core/legacy packages
legacy boundary debt remains explicit and visible
```

## 9. Gate 1.2 execution order

```text
1.2-1 Boundary Freeze + AST Contracts
1.2-2 SQLAlchemy Repository Implementations
1.2-3 SQLAlchemy UnitOfWork + transaction semantics
1.2-4 Application Services
1.2-5 API/Worker Composition Roots + legacy cutover
1.2-6 Boundary Regression / acceptance
```

No Gate 1.2 slice may bypass Gate 1.1 database constraints or import
`experiments/*` into formal runtime code.

## 10. Acceptance for Gate 1.2-1

```text
A. Gate 1.1 is closed PASS                                  PASS
B. dependency graph documented                              PASS
C. repository location/role frozen                          PASS
D. UnitOfWork transaction boundary frozen                   PASS
E. application service role frozen                          PASS
F. composition-root target frozen                           PASS
G. legacy API/worker/service debt explicitly quarantined    PASS
H. AST boundary contract tests pass                         PENDING LOCAL EVIDENCE
I. full Gate 1 contract suite remains green                 PENDING LOCAL EVIDENCE
```

Gate 1.2-1 becomes PASS only after H-I have local execution evidence.
Gate 1.2 overall remains CURRENT until all later slices pass.
