# Gate 1.2-6 — Boundary Regression / Acceptance

Status: **PASS / CLOSED**

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

The final acceptance contracts cover the accepted Gate 0 oracle minimums, Gate 1
full-suite minimum, Alembic head, UTF-8 offline SQL compilation, formal runtime
import direction, composition-root thinness, and preservation of Gate 0A
DEGRADED.

## 4. Accepted local evidence

User-local acceptance completed successfully:

```text
Dedicated Gate 1.2 acceptance contracts: 6 / 6 PASS
Complete Gate 1 formal suite:           111 / 111 PASS
Gate 1.2 deterministic regression probe: PASS
```

The regression probe also verified:

```text
Gate 0B deterministic oracle >= 37 tests
Gate 0C deterministic oracle >= 65 tests
Gate 0D deterministic oracle >= 54 tests
Gate 0E deterministic oracle >= 15 tests
Alembic head == c91e8d2f4a10
UTF-8 offline SQL compilation PASS
```

It deliberately performed no real provider/network resend and did not fabricate
the deferred Gate 0A lifecycle evidence.

## 5. Legacy debt treatment

Gate 1.2 final acceptance does **not** claim that every inherited API/worker file
has already been semantically replaced.

The accepted rule remains:

```text
formal stage_letter runtime never imports legacy outer packages
new orchestration enters through formal services/ports
legacy routers/workers stay quarantined migration debt
later gates own their semantic replacement
```

Residual debt remains visible rather than hidden or copied inward.

## 6. Final acceptance result

```text
A. Gate 1.2-5 is PASS                                  PASS
B. dedicated Gate 1.2 acceptance contracts            PASS / 6
C. complete Gate 1 formal suite                       PASS / 111
D. Gate 0B/0C/0D/0E deterministic regression          PASS
E. Alembic head == c91e8d2f4a10                       PASS
F. UTF-8 offline SQL compilation                       PASS
G. Gate 0A remains DEGRADED                            PRESERVED
H. no real provider resend/network dependency          PRESERVED
```

Gate 1.2-6: **PASS / CLOSED**.

Gate 1.2: **PASS / CLOSED**.

Next: Gate 1.3 — Platform Adapter Framework.

## 7. Preserved stop rules

The accepted Gate must not later be weakened by:

```text
lowering accepted Gate 0 oracle minimums to hide a regression
formal runtime importing api/workers/core/platform_adapters/experiments
application importing concrete infrastructure/framework code
changing UNKNOWN semantics to satisfy legacy behavior
fabricating lifecycle evidence to upgrade Gate 0A
rewriting accepted migration history instead of forward-fixing code
provider/network resend merely to make deterministic regression pass
```
