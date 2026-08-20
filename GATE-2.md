# Gate 2 — Detection Engine

## Gate 2.0 — Baseline / Boundary Freeze

Status: CURRENT

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

### Gate 2 slices

- **2.0** Baseline / Boundary Freeze.
- **2.1** Due Selection + HOT/WARM/COLD Scheduling Policy.
- **2.2** Per-Platform Runtime Isolation + Rate Limits + Retry Classification.
- **2.3** Probe Telemetry + Platform Health Persistence.
- **2.4** Degrade / Circuit-Breaker Policy + Recovery + Administrative Disable.
- **2.5** Restart / Multi-Worker / Capacity Acceptance.

### Gate 2.0 acceptance

- Gate 2 boundary tests PASS.
- Complete Gate 1 regression remains `435 / 435` PASS.
- Alembic head remains `a63f4b2d9e71`; Gate 2.0 adds no migration.
- No provider/network calls are required for Gate 2.0.

Gate 2.0 closes only the architectural boundary. It does not claim tier cadence,
health transitions, rate limits, or capacity are implemented until their later
slices pass.
