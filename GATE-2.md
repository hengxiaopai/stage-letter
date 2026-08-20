# Gate 2 — Detection Engine

## Gate 2.0 — Baseline / Boundary Freeze

Status: PASS / CLOSED

Gate 1 closed with the accepted baseline `435 / 435` and migration head
`a63f4b2d9e71`. Gate 2 extends the detection runtime; it must not rewrite the
accepted Gate 1 live-truth or notification semantics.

### Reuse from Gate 1

- `MonitoringTargetApplicationService` for deterministic enabled-account discovery.
- `MonitoringProbeApplicationService` as the only provider-to-durable-observation ingress.
- `workers.monitoring.MonitoringScheduler` for bounded concurrency, stable logical
  probe IDs, and conservative transport retry mechanics.
- The accepted four-platform formal adapter registry (`douyin`, `bilibili`, `huya`,
  `douyu`).
- `LiveObservationConsumptionApplicationService` + `LiveStateReducer` + transition
  persistence for interpretation of already-durable observations.

### Frozen boundaries

1. **Provider failure is not live truth.** Timeout/network/429/auth/schema ambiguity
   may produce provider diagnostics or `UNKNOWN`; it must never fabricate `OFFLINE`.
2. **Canonical live truth has one ingress.** A provider result becomes a durable
   `LiveObservation` before the reducer may interpret it.
3. **Provider I/O stays outside database transactions.** Operational locks/limits
   must not wrap network calls inside a SQLAlchemy UnitOfWork.
4. **Detection metadata is operational, not canonical.** Polling tier, due time,
   latency, provider failures and platform health may influence scheduling only;
   they do not directly create/close sessions or events.
5. **Gate 1 Base remains frozen.** Existing physical legacy tables/columns
   (`platform_health`, `probe_runs`, `platform_accounts.polling_tier`) may be mapped
   through a separate Gate 2 persistence boundary, as Gate 1.6 did for grants;
   they are not silently promoted into the ten-table canonical Base.
6. **Legacy probe worker is quarantined.** `workers/probe/worker.py` is
   `LEGACY_REFERENCE_ONLY`. Gate 2 formal runtime must not import `core.models`,
   `core.live_session_engine`, or legacy `platform_adapters` from it.
7. **Cross-platform isolation is mandatory.** Saturation/failure in one platform
   must not consume all global capacity or stop healthy platforms.
8. **Notification remains independent.** Detection code does not send WeChat
   messages or mutate notification delivery state.
9. **No exactly-once claims.** Durable observation/event identities may be
   idempotent; provider/worker execution is not claimed exactly once.
10. **Gate 0A remains DEGRADED.** Gate 2 synthetic/controlled evidence cannot close
    the missing same-creator real-provider lifecycle evidence.

### Gate 2.0 acceptance

- Boundary tests PASS.
- Complete Gate 1 + Gate 2.0 regression: `442 passed, 173 subtests passed`.
- Alembic head remained `a63f4b2d9e71`.
- No provider/network calls were required.

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

Status: CURRENT

### Operational telemetry contract

One `ProbeTelemetryRecord` describes one logical `monitor:` execution after the
Gate 2.2 coordinator finishes. It records account/platform identity, start/end,
total latency, attempt count, operational success/failure, resulting observation
status when available, and a normalized failure kind when execution failed.

`success=True` means the formal provider operation completed and durable ingress
succeeded. A resulting `UNKNOWN` LiveObservation is therefore still an
operationally successful probe; UNKNOWN is not silently reclassified as failure
or OFFLINE.

Raw exception/provider messages are not persisted by the formal telemetry path.
`error_message` receives only the normalized failure kind, reducing secret/token
leak risk.

### Persistence boundary

`SQLAlchemyDetectionTelemetryRepository` uses independent SQLAlchemy Core
`MetaData` and the existing physical `probe_runs` / `platform_health` tables. It
is deliberately outside the frozen Gate 1 canonical Base.

Formal Gate 2.3 probe rows are tagged with `telemetry_schema = gate2.3` in JSON.
Platform 24-hour success/error counts and average latency are recomputed from
only those tagged rows in the trailing 24-hour window; legacy probe rows are not
silently mixed into the new formal metrics.

Gate 2.3 updates operational evidence only:

- success sets `last_success_at` and resets `consecutive_failures`;
- failure sets `last_failure_at` and increments `consecutive_failures`;
- success/error/latency 24h metrics are refreshed;
- an absent platform-health row starts as `HEALTHY`;
- an existing `platform_health.state` is preserved exactly.

**Gate 2.3 does not perform HEALTHY/DEGRADED/DISABLED transitions. Gate 2.4 owns
those circuit-breaker decisions.**

### Runtime isolation from truth

`DetectionCycleRuntime` appends telemetry only after the provider/durable-ingress
outcome exists. Telemetry persistence failure is surfaced separately through
`telemetry_failures`; it cannot reverse a successfully persisted observation,
create/close a session/event, or touch notification delivery.

### Gate 2.3 acceptance

- Dedicated telemetry/health tests PASS.
- Complete Gate 1 + Gate 2 regression remains green.
- Controlled PostgreSQL acceptance writes one synthetic operational telemetry row,
  verifies `probe_runs` + `platform_health`, then removes the synthetic row and
  restores the exact pre-probe health snapshot.
- Acceptance makes no provider/notification call and reports no live-truth mutation.
- Alembic head remains `a63f4b2d9e71`; Gate 2.3 adds no migration.
- No worker/provider exactly-once or Gate 0A lifecycle claim is introduced.

### Remaining Gate 2 slices

- **2.4** Degrade / Circuit-Breaker Policy + Recovery + Administrative Disable.
- **2.5** Restart / Multi-Worker / Capacity Acceptance.
