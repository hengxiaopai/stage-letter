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

### Contract

Gate 2.1 answers only **which enabled platform accounts are eligible to probe now**.
It does not change live truth, health state, retry classification, notifications,
or provider semantics.

Accepted default cadence:

- `HOT`: 30 seconds
- `WARM`: 60 seconds
- `COLD`: 300 seconds

Legacy `NULL`/blank tier values normalize to `WARM`. Unknown non-blank tier values
fall back to `COLD`, preventing corrupted metadata from increasing provider load.
A never-probed enabled account is due immediately. A probed account becomes due at
`last_probe_at + tier_interval`; the boundary instant is inclusive.

### Persistence boundary

`platform_accounts.polling_tier` remains operational metadata and is read through
an independent SQLAlchemy Core `MetaData`, not added to the frozen Gate 1 Base.
The last formal monitoring probe time is derived from the latest durable
`live_observations.created_at` whose `observation_id` starts with `monitor:`.
This reuses the accepted durable probe ingress instead of reviving legacy
`last_checked_at` / `last_status` truth coupling.

### Runtime reuse

`workers/detection_composition.py` wires the Gate 2 due-aware target service into
Gate 1's already accepted `MonitoringScheduler` and
`MonitoringProbeApplicationService`. Therefore provider I/O remains outside the
DB transaction and every provider result still enters through durable
`LiveObservation` first.

### Gate 2.1 acceptance

- Complete Gate 1 + Gate 2 regression: `452 passed, 173 subtests passed`.
- Read-only PostgreSQL due-selection probe PASS over 15 enabled accounts.
- All 15 existing accounts normalized to WARM and were due because no formal
  `monitor:` observation had yet been persisted for them.
- Accepted cadence remained HOT=30s, WARM=60s, COLD=300s.
- Alembic head remained `a63f4b2d9e71`; Gate 2.1 added no migration.
- Probe made no provider/notification calls and performed no DB writes.

## Gate 2.2 — Per-Platform Runtime Isolation + Rate Limits + Retry Classification

Status: CURRENT

### Contract

Gate 2.2 controls **how a due provider operation is allowed to execute**. It does
not decide live truth and does not own platform-health persistence yet.

- Global execution concurrency is bounded.
- Every platform has its own semaphore; waiting work from one saturated platform
  does not occupy all global execution capacity.
- Provider start rate is limited independently per platform. Waiting for the next
  rate window happens before execution semaphores are acquired.
- Default formal start rate is 1 request/second/platform and is configurable by
  explicit per-platform policy.
- Retries preserve the exact same `MonitoringProbeRequest` / `monitor:` probe ID.
- Exponential backoff remains bounded.
- Only explicit transient failures retry automatically:
  `TIMEOUT`, `NETWORK`, `RATE_LIMITED`, `UPSTREAM_ERROR`, plus Python
  `TimeoutError` / `ConnectionError`.
- `AUTH_REQUIRED`, `FORBIDDEN`, `CAPTCHA_REQUIRED`, `PARSE_ERROR`,
  `SCHEMA_DRIFT`, `AMBIGUOUS`, `NOT_FOUND`, `UNKNOWN` stop without blind retry.
- Cancellation is never swallowed by the retry loop.
- Retry exhaustion returns the original failure and never fabricates OFFLINE or
  another live-state value.

### Formal runtime

`workers/detection_runtime.py` combines Gate 2.1 due targets with the Gate 2.2
execution coordinator, while retaining Gate 1.4's
`MonitoringProbeApplicationService` as the only provider-to-durable-observation
ingress. `UNKNOWN` remains a valid durable observation and is not treated as a
transport failure.

### Gate 2.2 acceptance

- Dedicated runtime-isolation/retry tests PASS.
- Complete Gate 1 + Gate 2 regression remains green.
- Deterministic Gate 2.2 runtime policy probe PASS.
- Alembic head remains `a63f4b2d9e71`; Gate 2.2 adds no migration.
- Acceptance probe performs no provider/notification call and no database write.
- No exactly-once or Gate 0A lifecycle claim is introduced.

### Remaining Gate 2 slices

- **2.3** Probe Telemetry + Platform Health Persistence.
- **2.4** Degrade / Circuit-Breaker Policy + Recovery + Administrative Disable.
- **2.5** Restart / Multi-Worker / Capacity Acceptance.
