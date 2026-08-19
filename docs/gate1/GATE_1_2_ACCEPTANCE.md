# Gate 1.2-6 — Boundary Regression / Acceptance

Status: **CURRENT / FINAL REGRESSION ASSETS LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.2-5 PASS.

## 1. Purpose

Gate 1.2-6 is the final acceptance slice for Repository / Service Boundaries. It
does not add new business behavior. It proves that the dependency graph,
repositories, UnitOfWork, application services, composition roots, accepted Gate
0 semantics, and current schema head remain mutually compatible.

## 2. Accepted entry state

```text
Gate 1.2-1  PASS / dependency boundary freeze
Gate 1.2-2  PASS / SQLAlchemy repositories + PostgreSQL evidence
Gate 1.2-3  PASS / UnitOfWork + transaction/PostgreSQL evidence
Gate 1.2-4  PASS / application services
Gate 1.2-5  PASS / API + worker composition roots
```

Gate 0A remains inherited **DEGRADED** because the real lifecycle evidence gap is
still deferred. Gate 1.2 does not reinterpret that status.

## 3. Final regression assets

```text
tests/gate1/test_gate12_acceptance.py
scripts/gate12_regression_probe.py
```

The acceptance contracts add six final checks covering:

```text
accepted Gate 0 oracle minimums remain pinned
Gate 1 full-suite minimum is pinned to the post-acceptance count
Alembic head remains c91e8d2f4a10
UTF-8 offline SQL compilation remains part of final regression
formal stage_letter runtime has no inward dependency on outer/legacy packages
application remains infrastructure/framework free
composition roots remain thin and do not cross-import
Gate 1.2 documentation preserves Gate 0A DEGRADED and slice progression
```

## 4. Deterministic regression probe

Run:

```text
python scripts/gate12_regression_probe.py
```

The probe executes:

```text
Gate 0B deterministic oracle >= 37 tests
Gate 0C deterministic oracle >= 65 tests
Gate 0D deterministic oracle >= 54 tests
Gate 0E deterministic oracle >= 15 tests
Gate 1 formal contracts      >= 111 tests
Alembic head                 == c91e8d2f4a10
UTF-8 offline SQL compilation PASS
```

It deliberately does not perform real provider/network calls, repeat WeChat
sends, or manufacture the deferred Gate 0A lifecycle evidence.

## 5. Legacy debt treatment

Gate 1.2 final acceptance does **not** claim that every inherited API/worker file
has already been semantically replaced.

The accepted rule is narrower and enforceable:

```text
formal stage_letter runtime never imports legacy outer packages
new orchestration enters through formal services/ports
legacy routers/workers stay quarantined migration debt
later gates own their semantic replacement
```

Residual debt therefore remains visible rather than being hidden or copied into
the formal package.

## 6. PASS criteria

Gate 1.2-6 and Gate 1.2 may close PASS only after all of the following user-local
evidence is established:

```text
A. Gate 1.2-5 is PASS                                  PASS
B. dedicated Gate 1.2 acceptance contracts            PENDING / 6 tests
C. complete Gate 1 formal suite                       PENDING / 111 tests
D. Gate 0B/0C/0D/0E deterministic regression          PENDING
E. Alembic head == c91e8d2f4a10                       PENDING
F. UTF-8 offline SQL compilation                       PENDING
G. Gate 0A remains DEGRADED                            PRESERVED
H. no real provider resend/network dependency          PRESERVED
```

Until B-F pass, Gate 1.2-6 remains **CURRENT** and Gate 1.2 remains **CURRENT**.

## 7. Stop rules

Stop with FAIL/BLOCKED rather than weakening acceptance if final regression
requires any of:

```text
lowering an accepted Gate 0 oracle minimum to hide a regression
removing boundary tests because legacy code conflicts with them
formal runtime importing api/workers/core/platform_adapters/experiments
application importing concrete infrastructure/framework code
changing UNKNOWN semantics to satisfy legacy behavior
fabricating lifecycle evidence to upgrade Gate 0A
changing current schema history instead of fixing forward code
provider/network resend merely to make deterministic regression pass
```
