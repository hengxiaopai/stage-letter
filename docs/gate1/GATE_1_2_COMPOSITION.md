# Gate 1.2-5 — API / Worker Composition Roots + Legacy Cutover

Status: **CURRENT / FORMAL ROOTS LANDED / LOCAL EVIDENCE + CUTOVER ACCEPTANCE PENDING**

Entry authority: Gate 1.2-4 PASS.

## 1. Purpose

Gate 1.2-5 makes API and worker processes the only outer composition roots that
may couple formal application services to concrete infrastructure.

Canonical direction:

```text
api / workers
  -> application services
      -> application ports
          <- infrastructure implementations
              -> PostgreSQL
```

`stage_letter/domain` and `stage_letter/application` remain unaware of FastAPI,
workers, SQLAlchemy implementations, provider adapters, and legacy runtime code.

## 2. Landed roots

```text
api/composition.py
workers/composition.py
```

Both roots construct the accepted services:

```text
CreatorApplicationService
FollowApplicationService
LiveObservationApplicationService
```

through `SQLAlchemyUnitOfWork` using a supplied async session factory.

The API process now exposes the formal bundle at:

```text
app.state.stage_letter_services
```

via `build_api_services(async_session)`.

This is a dependency cutover seam, not a claim that every existing HTTP route
already uses the formal service layer.

## 3. Legacy boundary inventory

The repository still contains inherited runtime owners that pre-date the formal
Gate 1 architecture, including:

```text
api/routers/*
api/services/*
workers/probe/worker.py
workers/notify/*
core/*
platform_adapters/*
```

Examples observed during Gate 1.2-5 inspection:

- `api/routers/subscriptions.py` still owns direct ORM mutations, legacy Anchor /
  UserSubscription semantics, and direct commit.
- `workers/probe/worker.py` still combines scheduling, adapter invocation,
  legacy state-machine calls, health logic, and direct persistence.

Those modules are **legacy boundary debt**. They remain operational during the
staged migration but are not authoritative templates for new formal runtime
code.

## 4. Cutover rule

From Gate 1.2-5 onward:

```text
new API/worker orchestration
-> must enter through formal application services / ports

formal stage_letter runtime
-> must never import api/workers/core/platform_adapters/experiments

legacy API/worker modules
-> may remain temporarily
-> must not be imported inward by formal modules
-> must not be extended with new canonical domain rules
```

Actual semantic migration remains gate-owned:

```text
platform adapters/provider truth            Gate 1.3
scheduler/source collection                 Gate 1.4
state/session/event persistence runtime      Gate 1.4 / 1.5
notification queue/provider execution        Gate 1.6
public HTTP API contract                     Gate 1.7
```

Gate 1.2-5 therefore freezes the wiring seam without prematurely copying legacy
state/provider behavior into formal services.

## 5. API root

`api/composition.py` is allowed to know both:

```text
stage_letter.application.services
stage_letter.infrastructure.db.uow
```

It must not own domain transition logic, instantiate providers, interpret raw
platform state, or translate UNKNOWN to OFFLINE.

`api/main.py` may own concrete bootstrap coupling such as the current async
session factory because it is an outer composition root.

## 6. Worker root

`workers/composition.py` provides the equivalent service/UoW seam for future
formal workers.

The existing `workers/probe/worker.py` is deliberately not rewritten in Gate
1.2-5 because it mixes responsibilities owned by Gates 1.3-1.5. Replacing it
before those contracts exist would only copy legacy behavior into a new path.

## 7. Contract tests

Landed:

```text
tests/gate1/test_composition_roots.py
```

The tests verify:

```text
API root builds only formal application services
worker root builds only formal application services
all services in one root share the same UnitOfWork factory
roots do not import domain or legacy runtime packages
API and worker roots do not depend on each other
api/main.py exposes the formal service bundle
legacy routers remain present during staged cutover
```

## 8. Acceptance

Gate 1.2-5 PASS requires:

```text
A. Gate 1.2-4 PASS                                      PASS
B. API composition root landed                          PASS / CODE
C. Worker composition root landed                       PASS / CODE
D. API bootstrap exposes formal service bundle          PASS / CODE
E. formal roots contain no domain/legacy business logic CONTRACT LANDED
F. legacy boundary debt explicitly quarantined          PASS / DOC
G. composition-root contract tests pass                 PENDING LOCAL EVIDENCE
H. full Gate 1 suite remains green                      PENDING LOCAL EVIDENCE
```

Gate 1.2-5 remains **CURRENT** until G-H pass.

## 9. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
formal application importing concrete infrastructure
formal stage_letter runtime importing api/workers/core/platform_adapters/experiments
API/worker root implementing state-machine/domain rules
copying legacy 7-state status semantics into formal LiveStatus
UNKNOWN -> OFFLINE coercion
provider calls inside application DB transactions
premature rewrite of probe worker before Gate 1.3/1.4 contracts
claiming legacy routers are migrated when they still mutate ORM directly
```
