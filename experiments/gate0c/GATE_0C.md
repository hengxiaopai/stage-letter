# Gate 0C — Stability + Platform Health

Status: **IN PROGRESS**

## Scope

Gate 0C validates operational stability around the normalized live-status probes that feed Gate 0B.

It does **not** redefine creator live state. The key boundary is:

```text
provider probe failure
    -> provider health may degrade
    -> normalized creator observation may be UNKNOWN
    -> MUST NOT become OFFLINE merely because the provider is unhealthy
```

Gate 0B remains the owner of canonical LiveSession behavior.

## Gate 0C plan

```text
0C-1 Provider Health Engine         CURRENT
0C-2 Poll / retry / backoff policy  NEXT
0C-3 Fault-injection recovery       NOT STARTED
0C-4 Source-composition policy      NOT STARTED
```

The initial canonical-status candidate remains the self-hosted StreamGet profile/sec_uid path proven in Gate 0A. TikHub/F2 may provide corroboration or metadata enrichment, but health semantics are provider-agnostic and must not assume any one source is permanently available.

---

## Gate 0C-1 — Provider Health Engine

One `HealthEngine` represents one provider route / polling source.

Health state is deliberately separate from LIVE/OFFLINE/UNKNOWN:

```text
UNPROVEN
HEALTHY
DEGRADED
UNAVAILABLE
```

Gate acceptance defaults:

```text
degraded_after_failures    = 2
unavailable_after_failures = 5
recover_after_successes    = 2
```

These values are Gate test parameters, **not frozen production tuning**.

### Health inputs

A provider probe contributes one health sample:

```text
SUCCESS
    decisive provider request completed successfully

FAILURE
    timeout / rate limit / auth block / challenge / transport /
    parse-schema drift / upstream failure / ambiguous response / other
```

Normalized failure classes:

```text
TIMEOUT
RATE_LIMIT
AUTH_BLOCK
CHALLENGE
TRANSPORT
PARSE_SCHEMA
UPSTREAM
AMBIGUOUS
OTHER
```

The provider-specific `error_type` is retained as diagnostic metadata.

### Transition rules

```text
UNPROVEN + first SUCCESS -> HEALTHY

HEALTHY + one FAILURE -> remain HEALTHY, failure streak = 1
second consecutive FAILURE -> DEGRADED
fifth consecutive FAILURE  -> UNAVAILABLE

DEGRADED / UNAVAILABLE
    require consecutive successful probes to recover
    one lucky success is insufficient
```

A failure can never improve health severity.

### Recovery semantics

Default recovery requires two consecutive successes:

```text
DEGRADED + SUCCESS #1     -> DEGRADED
DEGRADED + SUCCESS #2     -> HEALTHY

UNAVAILABLE + SUCCESS #1  -> UNAVAILABLE
UNAVAILABLE + SUCCESS #2  -> HEALTHY
```

A failed recovery resets the success streak and does not silently improve an unavailable source.

### Idempotency

Each health sample has a `sample_id`.

```text
duplicate sample_id
    -> DUPLICATE
    -> no counters changed
    -> no health transition
```

The engine exposes `HealthSnapshot` / `HealthEngine.from_snapshot()` so Gate 0C-2 can persist health state without moving operational semantics into a database implementation.

### Diagnostic facts retained

```text
last_sample_at
last_success_at
last_failure_at
last_failure_class
last_error_type
last_latency_ms
success_count
failure_count
consecutive_successes
consecutive_failures
```

A later success does not erase the last failure diagnostic; current health state and historical diagnostic facts are distinct.

### Critical safety boundary

`HealthEngine` intentionally contains **no creator LIVE/OFFLINE state and no LiveSession mutation API**.

Therefore:

```text
provider TIMEOUT       != creator OFFLINE
provider HTTP 429      != creator OFFLINE
provider schema drift  != creator OFFLINE
provider challenge     != creator OFFLINE
provider unavailable   != creator OFFLINE
```

These conditions belong to platform/source health and usually normalize to creator `UNKNOWN` at the adapter boundary.

---

## Gate 0C-1 acceptance matrix

```text
01 new provider route starts UNPROVEN                    PENDING CI
02 first success proves HEALTHY                          PENDING CI
03 one failure does not overreact                        PENDING CI
04 two consecutive failures -> DEGRADED                  PENDING CI
05 five consecutive failures -> UNAVAILABLE              PENDING CI
06 DEGRADED needs two successes to recover               PENDING CI
07 UNAVAILABLE needs two successes to recover            PENDING CI
08 failed recovery does not improve UNAVAILABLE          PENDING CI
09 duplicate sample id is idempotent                     PENDING CI
10 normalized failure reason retained                    PENDING CI
11 success preserves last-failure diagnostic             PENDING CI
12 snapshot restore preserves health/idempotency         PENDING CI
13 never-proven source can degrade/unavailable           PENDING CI
14 all failure classes follow health-only semantics      PENDING CI
15 thresholds are configurable and validated             PENDING CI
16 impossible sample metadata rejected                   PENDING CI
```

---

## Next: Gate 0C-2 — Poll / retry / backoff policy

After 0C-1 passes, Gate 0C-2 should define the scheduler behavior without coupling it to UI or notifications.

Questions to freeze:

```text
normal polling interval
DEGRADED retry cadence
UNAVAILABLE backoff ceiling
jitter policy to avoid synchronized polling
rate-limit-specific cool-down
when to attempt recovery probes
whether health state persists across process restart
how provider health influences source selection without mutating creator state
```

Do not hard-code aggressive retry values until rate-limit and real-world evidence supports them.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C-1  IN PROGRESS
Gate 0C    IN PROGRESS
Gate 0D    NOT STARTED
Gate 0E    NOT STARTED
```
