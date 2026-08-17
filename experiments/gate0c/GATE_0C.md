# Gate 0C — Stability + Platform Health

Status: **IN PROGRESS**

## Scope

Gate 0C validates operational stability around normalized live-status probes before they reach Gate 0B canonical state handling.

The non-negotiable boundary is:

```text
provider/source failure
    -> source health may degrade
    -> creator observation may normalize to UNKNOWN
    -> MUST NOT become OFFLINE merely because the source is unhealthy
```

Gate 0B remains the owner of canonical LiveSession behavior.

## Gate 0C plan

```text
0C-1 Platform / Provider Health Policy     PASS
0C-2 Poll / retry / backoff policy         CURRENT
0C-3 Fault-injection recovery              NOT STARTED
0C-4 Source-composition policy             NOT STARTED
```

The initial canonical-status candidate remains the self-hosted StreamGet profile/sec_uid path proven in Gate 0A. TikHub/F2 may provide corroboration or metadata enrichment, but Gate 0C health semantics are provider-agnostic.

---

## Gate 0C-1 — Platform / Provider Health Policy — PASS

Canonical implementation:

```text
experiments/gate0c/platform_health.py
experiments/gate0c/test_platform_health.py
```

One `HealthTracker` represents one monitoring scope, normally one provider/account route.

### Health state is separate from creator state

```text
HealthState:
STARTING | HEALTHY | DEGRADED | UNAVAILABLE

CanonicalStatus:
LIVE | OFFLINE | UNKNOWN
```

A provider-health transition never rewrites a creator status.

Gate acceptance defaults:

```text
degrade_after_failures          = 2
unavailable_after_failures      = 4
recover_after_clean_successes   = 2
slow_latency_ms                 = 5000
```

These values are Gate test parameters, **not frozen production tuning**.

### Normalized provider failures

```text
TIMEOUT
NETWORK
RATE_LIMIT
PARSE
AUTH
BLOCKED
EMPTY
OTHER
```

`AUTH` and `BLOCKED` are hard failures and make the route immediately `UNAVAILABLE` in the Gate policy. Other failures use consecutive-failure hysteresis.

### Core transition semantics

```text
STARTING + clean decisive LIVE/OFFLINE
    -> HEALTHY

HEALTHY + one transient UNKNOWN/failure
    -> remain HEALTHY

second consecutive general failure
    -> DEGRADED

fourth consecutive general failure
    -> UNAVAILABLE

DEGRADED / UNAVAILABLE
    -> require two consecutive clean successes for HEALTHY
```

A single lucky response is insufficient for full recovery.

A decisive response whose latency is above `slow_latency_ms` preserves the creator LIVE/OFFLINE fact but makes health `DEGRADED`. A slow recovery from `UNAVAILABLE` therefore recovers only to `DEGRADED`, not directly to `HEALTHY`.

### UNKNOWN safety

```text
UNKNOWN + TIMEOUT     -> health failure, creator remains UNKNOWN
UNKNOWN + NETWORK     -> health failure, creator remains UNKNOWN
UNKNOWN + RATE_LIMIT  -> health failure, creator remains UNKNOWN
UNKNOWN + PARSE       -> health failure, creator remains UNKNOWN
UNKNOWN + no code     -> failure kind EMPTY, creator remains UNKNOWN
```

A failed probe is invalid if it simultaneously claims a decisive LIVE/OFFLINE fact.

### Ordering / delayed requests

Health ordering uses probe `started_at` rather than completion time.

```text
duplicate sample_id
    -> DUPLICATE
    -> no health mutation

started_at < watermark
    -> STALE
    -> no streak / health mutation

started_at == watermark
    -> not automatically stale
```

This prevents an old slow request that finishes late from regressing health after a newer probe has already completed.

### Restart boundary

`HealthSnapshot` / `HealthTracker.from_snapshot()` preserve:

```text
health state
consecutive failure / recovery streaks
ordering watermark
sample-id idempotency
last failure kind
health counters
```

Gate 0C-2 may therefore persist scheduler/health state without moving health semantics into a database implementation.

### Partial-platform aggregation

```text
all scopes HEALTHY       -> HEALTHY
all scopes UNAVAILABLE   -> UNAVAILABLE
all scopes STARTING      -> STARTING
mixed population         -> DEGRADED
```

A failure on one creator/provider scope must not falsely claim that the entire platform is unavailable.

### Gate 0C-1 acceptance — PASS 19/19

```text
01 first decisive probe establishes HEALTHY                PASS
02 one transient UNKNOWN does not immediately degrade      PASS
03 two consecutive failures -> DEGRADED                    PASS
04 four consecutive failures -> UNAVAILABLE                PASS
05 AUTH/BLOCKED -> immediate UNAVAILABLE                    PASS
06 UNAVAILABLE needs two clean successes for HEALTHY       PASS
07 slow decisive status preserved while health degrades    PASS
08 UNKNOWN without error code remains UNKNOWN              PASS
09 stale delayed failure cannot regress newer health       PASS
10 duplicate classification precedes stale                 PASS
11 newer UNKNOWN watermark blocks older failure count      PASS
12 snapshot restore preserves recovery/idempotency         PASS
13 partial platform failure aggregates DEGRADED            PASS
14 all unavailable aggregates UNAVAILABLE                  PASS
15 all healthy aggregates HEALTHY                          PASS
16 equal start timestamp not falsely stale                 PASS
17 failed probe cannot claim decisive LIVE/OFFLINE         PASS
18 slow recovery reaches DEGRADED, not HEALTHY             PASS
19 invalid thresholds rejected                             PASS
```

Clean CI evidence after duplicate prototype cleanup:

```text
workflow  Gate 0C Health Smoke
run       32007232769
head      96b8cffe917b51cd41ddaacf281bb9b58ac7fa09
result    completed / success
suite     19 tests / 19 PASS
```

Intermediate failed runs during the health-model cleanup are test-tooling/repository-shape failures and are superseded by the clean single-model run above. They are not counted as platform-health semantic evidence.

---

## Gate 0C-2 — Poll / retry / backoff policy — CURRENT

Gate 0C-2 defines scheduler decisions only. It must not perform provider HTTP calls and must not mutate creator LIVE/OFFLINE state.

The policy output should be a next-poll delay / cooldown decision derived from:

```text
HealthState
FailureKind | null
consecutive failure count
optional deterministic jitter input
```

Required behavior:

```text
HEALTHY
    -> normal polling cadence

DEGRADED
    -> slower / conservative cadence

UNAVAILABLE
    -> exponential recovery-probe backoff with a hard ceiling

RATE_LIMIT
    -> explicit minimum cooldown override

AUTH / BLOCKED
    -> long recovery-probe cooldown; never tight-loop

jitter
    -> bounded and testable; avoid synchronized polling bursts

successful recovery
    -> backoff resets through current health state / streak facts
```

Gate timing values remain configurable acceptance parameters until real provider-rate-limit evidence exists. No aggressive production intervals are frozen here.

### 0C-2 acceptance targets

```text
01 HEALTHY uses normal cadence                              PENDING
02 DEGRADED uses conservative cadence                       PENDING
03 UNAVAILABLE backoff grows exponentially                  PENDING
04 backoff is capped                                        PENDING
05 RATE_LIMIT enforces minimum cooldown                     PENDING
06 AUTH/BLOCKED never tight-loop                            PENDING
07 bounded jitter never violates minimum cooldown           PENDING
08 deterministic jitter makes tests reproducible            PENDING
09 recovery/healthy state resets backoff                    PENDING
10 scheduling policy never emits creator LIVE/OFFLINE       PENDING
11 invalid policy configuration rejected                    PENDING
12 pure snapshot inputs produce deterministic decision      PENDING
```

---

## Later Gate 0C work

### 0C-3 Fault-injection recovery

Prove timeout, network break, parse/schema drift, rate-limit, blocked/auth failure and recovery sequences against the health + polling policy without producing fake live transitions.

### 0C-4 Source-composition policy

Freeze how canonical status, corroboration and metadata enrichment interact when one source is degraded/unavailable. Source selection may change; creator truth must still obey the normalized observation contract and `UNKNOWN != OFFLINE`.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C-1  PASS
Gate 0C-2  CURRENT
Gate 0C    IN PROGRESS
Gate 0D    NOT STARTED
Gate 0E    NOT STARTED
```
