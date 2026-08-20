# Gate 2 — Detection Engine

## Gate 2.0 — Baseline / Boundary Freeze

Status: PASS / CLOSED

Gate 1 closed with the accepted baseline `435 / 435` and migration head
`a63f4b2d9e71`. Gate 2 extends the detection runtime; it must not rewrite the
accepted Gate 1 live-truth or notification semantics.

Frozen boundaries remain: provider failure is not live truth; provider I/O stays
outside DB transactions; provider results enter through durable `LiveObservation`
first; detection metadata stays operational; the Gate 1 Base stays frozen; the
legacy `workers/probe/worker.py` remains `LEGACY_REFERENCE_ONLY`; notification is
independent; no exactly-once claim is introduced; Gate 0A remains DEGRADED.

Gate 2.0 acceptance froze `442 passed, 173 subtests passed` and migration head
`a63f4b2d9e71` with no provider/network requirement.

## Gate 2.1 — Due Selection + HOT/WARM/COLD Scheduling Policy

Status: PASS / CLOSED

Accepted cadence is HOT=30s, WARM=60s, COLD=300s. NULL/blank tier values use
WARM; corrupt non-blank values conservatively use COLD. Never-probed accounts are
due immediately and the due boundary is inclusive.

Gate 2.1 acceptance froze `452 passed, 173 subtests passed`, a read-only
PostgreSQL due-selection PASS across 15 enabled WARM accounts, no provider or
notification calls, no DB writes, and migration head `a63f4b2d9e71`.

## Gate 2.2 — Per-Platform Runtime Isolation + Rate Limits + Retry Classification

Status: PASS / CLOSED

Gate 2.2 controls how a due provider operation executes: bounded global and
per-platform concurrency, independent per-platform start-rate limiting, stable
logical probe identity across retries, and bounded exponential backoff.

Automatic retry is limited to explicit transient evidence: `TIMEOUT`, `NETWORK`,
`RATE_LIMITED`, `UPSTREAM_ERROR`, plus Python `TimeoutError` / `ConnectionError`.
Auth/forbidden/captcha/parse/schema/ambiguous/not-found/unknown evidence stops
without blind retry. Retry exhaustion never fabricates OFFLINE.

Gate 2.2 acceptance froze `463 passed, 173 subtests passed` and deterministic
runtime policy PASS: transient retry succeeded on attempt 2, auth stopped after
one attempt, 2 req/s start times were `[0.0, 0.5, 1.0]`, no provider/notification
call or DB write occurred, and migration head remained `a63f4b2d9e71`.

## Gate 2.3 — Probe Telemetry + Platform Health Persistence

Status: PASS / CLOSED

One formal `ProbeTelemetryRecord` describes one logical `monitor:` execution
after Gate 2.2 finishes. `success=True` means provider execution plus durable
ingress completed; a resulting `UNKNOWN` LiveObservation remains a successful
operational probe and is not rewritten as failure or OFFLINE.

Formal telemetry uses independent SQLAlchemy Core metadata over existing physical
`probe_runs` and `platform_health`. Gate 2.3-tagged rows (`telemetry_schema =
gate2.3`) alone feed formal 24-hour success/error/latency metrics. It records
last success/failure and consecutive failures but deliberately preserves the
existing platform-health state; Gate 2.4 owns circuit-breaker transitions.

Gate 2.3 acceptance froze `474 passed, 173 subtests passed`. Controlled PostgreSQL
acceptance persisted one synthetic operational row, verified `probe_runs` and
`platform_health`, then removed/restored all controlled evidence. Result:
`database_restored=true`, no provider/notification call, no live-truth mutation,
and migration head `a63f4b2d9e71`.

## Gate 2.4 — Degrade / Circuit Breaker / Recovery / Administrative Disable

Status: CURRENT

### State policy

Default operational thresholds are:

- failures 0-4: remain `HEALTHY`;
- failure 5: trip `DEGRADED`;
- while `DEGRADED`, automatic polling cadence is multiplied by 5;
- failure 20: trip `DISABLED`;
- `DISABLED` is sticky under late/racing probe results and is never automatically
  restored by a success that arrives after disable;
- explicit administrative enable moves `DISABLED -> DEGRADED` and resets
  `consecutive_failures` to 0 (half-open recovery);
- the next successful half-open probe moves `DEGRADED -> HEALTHY`;
- explicit administrative disable moves any platform to `DISABLED`.

This state machine is operational only. A circuit-breaker transition cannot
create/close `LiveSession` or `LiveEvent`, cannot mutate notification delivery,
and cannot fabricate OFFLINE.

### Scheduling integration

Gate 2.1 due selection now reads `platform_health.state` through the same separate
operational SQLAlchemy Core boundary:

- `HEALTHY`: normal HOT/WARM/COLD cadence;
- `DEGRADED`: base cadence x5;
- `DISABLED`: excluded from automatic target discovery;
- absent/blank health state: `HEALTHY`;
- corrupt non-blank state: conservatively `DEGRADED`, never full-rate HEALTHY.

A never-probed DEGRADED account remains eligible immediately so a newly enabled
half-open platform cannot deadlock waiting for historical probe metadata.

### Persistence and runtime

`SQLAlchemyDetectionHealthRepository` maps only the physical `platform_health`
table with independent Core metadata and row locks. Health-aware telemetry first
persists Gate 2.3 evidence, then applies the Gate 2.4 state transition. If either
operational persistence step fails, the already durable provider observation is
not rolled back and the provider is not retried because of telemetry/health work.

Explicit administrative disable/half-open-enable are separate application
operations and do not touch `platform_accounts.is_disabled`; per-account
administrative configuration and per-platform circuit health remain distinct.

### Gate 2.4 acceptance

- Dedicated circuit-breaker tests PASS.
- Complete Gate 1 + Gate 2 regression remains green.
- Controlled PostgreSQL probe proves HEALTHY at failure 4, DEGRADED at 5,
  DISABLED at 20, sticky DISABLED under a late success, administrative half-open,
  successful recovery to HEALTHY, and explicit administrative disable.
- Controlled PostgreSQL probe restores the exact original `platform_health` row.
- No provider/notification call and no canonical live-truth mutation.
- Alembic head remains `a63f4b2d9e71`; Gate 2.4 adds no migration.
- No exactly-once or Gate 0A lifecycle claim is introduced.

### Remaining Gate 2 slice

- **2.5** Restart / Multi-Worker / Capacity Acceptance.
