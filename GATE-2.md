# Gate 2 — Detection Engine

## Gate 2.0 — Baseline / Boundary Freeze

Status: PASS / CLOSED

Gate 1 closed with `435 / 435`. Gate 2 extends detection runtime without rewriting
accepted live-truth or notification semantics. Provider failure is not live truth,
provider I/O stays outside DB transactions, detection metadata stays operational,
the Gate 1 canonical Base stays frozen, the legacy probe worker remains reference
only, no exactly-once claim is introduced, and Gate 0A remains DEGRADED.

Gate 2.0 acceptance: `442 passed, 173 subtests passed`, migration head
`a63f4b2d9e71`.

## Gate 2.1 — Due Selection + HOT/WARM/COLD

Status: PASS / CLOSED

Accepted cadence: HOT=30s, WARM=60s, COLD=300s. Gate 2.1 acceptance froze
`452 passed, 173 subtests passed` and a read-only PostgreSQL due-selection PASS.

## Gate 2.2 — Runtime Isolation + Rate Limits + Retry Classification

Status: PASS / CLOSED

Global/per-platform execution is bounded and provider start rate is isolated by
platform. Only explicit transient failures retry automatically; auth/forbidden/
captcha/parse/schema/ambiguous/not-found/unknown evidence does not blind retry and
retry exhaustion never fabricates OFFLINE.

Gate 2.2 acceptance froze `463 passed, 173 subtests passed` and deterministic
runtime-isolation PASS.

## Gate 2.3 — Probe Telemetry + Platform Health Persistence

Status: PASS / CLOSED

Formal telemetry is operational evidence only. `UNKNOWN` can be a successful
provider/durable-ingress result and is not rewritten as failure/OFFLINE. Gate 2.3
uses independent Core mappings for `probe_runs` and `platform_health` and restores
controlled PostgreSQL acceptance evidence after verification.

Gate 2.3 acceptance froze `474 passed, 173 subtests passed`, PostgreSQL PASS, and
`database_restored=true`.

## Gate 2.4 — Degrade / Circuit Breaker / Recovery / Administrative Disable

Status: PASS / CLOSED

Default thresholds are failure 5 -> `DEGRADED`, failure 20 -> `DISABLED`, with
DEGRADED cadence x5. DISABLED is sticky under late probe results. Administrative
enable moves DISABLED -> DEGRADED with failures reset to zero; the next successful
half-open probe restores HEALTHY. Administrative disable explicitly moves a
platform to DISABLED.

Gate 2.4 acceptance froze `486 passed, 173 subtests passed`. Controlled PostgreSQL
acceptance proved HEALTHY at failure 4, DEGRADED at 5, DISABLED at 20, sticky
disable, half-open recovery, explicit disable, and exact health-row restoration.
Migration head remained `a63f4b2d9e71`.

## Gate 2.5 — Restart / Multi-Worker / Capacity Acceptance

Status: CURRENT

### Durable cross-worker lease

Gate 2.5 adds the operational table `detection_probe_leases` with one active row
per platform account. It is mapped through independent SQLAlchemy Core metadata and
is not added to the frozen Gate 1 Base.

Before provider execution, the formal detection runtime atomically tries to lease
the account. A live lease causes another worker/task to skip that account without
calling the provider. The lease is deliberately non-reentrant, including for the
same worker token, so duplicate tasks inside one process are also suppressed.

A normal completion releases its owned lease. A failed release does not replay or
retry the provider; the bounded lease remains until expiry. A crashed worker may
leave a lease behind, and another worker can take it only after expiry. Therefore
Gate 2.5 suppresses overlapping automatic probes under a valid lease but still
makes **no provider exactly-once claim** across crash/lease-expiry boundaries.

### Restart semantics

The lease is durable PostgreSQL state, so a fresh process observes and honors a
still-live lease after restart. Expired takeover is atomic. A previous/non-owner
worker cannot release a newer owner's lease.

If a crash occurs after provider contact but before durable observation, a later
worker may legitimately re-probe after lease expiry. If durable observation was
already committed, Gate 2.1 due selection observes that `monitor:` evidence after
lease expiry and avoids an immediate duplicate due probe.

### Capacity / isolation

Gate 2.2 global/per-platform semaphores remain authoritative execution limits.
Lease contention for one account/platform does not consume provider execution
capacity and does not prevent another healthy platform from making progress.

### Migration

Gate 2.5 introduces revision `b25d4e9c7a12`, revising `a63f4b2d9e71`, with:

- `detection_probe_leases.platform_account_id` primary key / FK;
- stable `monitor:` probe id;
- opaque worker owner token;
- acquired/expiry timestamps;
- expiry index for operational recovery/inspection.

No canonical live/session/event/notification schema is changed.

### Gate 2.5 acceptance

- Dedicated Gate 2.5 lease/restart/multi-worker tests PASS.
- Complete Gate 1 + Gate 2 regression remains green.
- PostgreSQL controlled race: two independent workers contend for one account and
  exactly one lease acquisition succeeds while the lease is live.
- Fresh-engine restart cannot acquire the live lease.
- Expired takeover succeeds atomically; old owner cannot release the new lease.
- Acceptance removes its controlled lease and reports `database_restored=true`.
- Capacity probe proves a healthy platform progresses while another platform is
  saturated at its per-platform limit.
- No real provider or notification call is required for Gate 2.5 acceptance.
- No live truth mutation, provider/worker exactly-once, or Gate 0A lifecycle claim.

Gate 2 closes only after all of the above evidence passes on PostgreSQL.
