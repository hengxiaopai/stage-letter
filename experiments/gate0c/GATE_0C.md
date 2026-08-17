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
0C-2 Poll / retry / backoff policy         PASS
0C-3 Fault-injection recovery              NEXT
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

`HealthSnapshot` / `HealthTracker.from_snapshot()` preserve health state, recovery/failure streaks, ordering watermark, sample-id idempotency, last failure kind and health counters.

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

Clean single-model CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007232769
head      96b8cffe917b51cd41ddaacf281bb9b58ac7fa09
result    completed / success
suite     19 tests / 19 PASS
```

Intermediate failed runs during duplicate prototype cleanup are superseded by this clean run and are not semantic Gate failures.

---

## Gate 0C-2 — Poll / retry / backoff policy — PASS

Canonical implementation:

```text
experiments/gate0c/poll_policy.py
experiments/gate0c/test_poll_policy.py
```

The polling policy is pure: it receives health/failure facts and returns only a next-poll timing decision. It performs no HTTP request, mutates no `HealthTracker`, and exposes no creator LIVE/OFFLINE field.

### Gate timing defaults

```text
STARTING                 30 s
HEALTHY                  60 s
DEGRADED                120 s
UNAVAILABLE base        180 s
UNAVAILABLE ceiling    1800 s
RATE_LIMIT minimum      600 s
AUTH/BLOCKED minimum    900 s
jitter                  +/-10%
```

These are acceptance-test parameters, **not production SLA or provider-safe values**.

### State-driven cadence

```text
STARTING
    -> normal initial probe cadence

HEALTHY
    -> normal cadence

DEGRADED
    -> conservative cadence

UNAVAILABLE
    -> RECOVERY_PROBE mode
    -> exponential backoff using the current failure streak
    -> hard ceiling
```

Default unavailable sequence for failure streak 1..5 is:

```text
180 -> 360 -> 720 -> 1440 -> 1800(capped)
```

Once health recovers to `HEALTHY`, old failure streak input cannot keep the unavailable backoff active; health state is the controlling scheduler fact.

### Provider-safe cooldown overrides

```text
RATE_LIMIT
    -> minimum 600 s

AUTH / BLOCKED
    -> minimum 900 s
```

The minimum cooldown is applied **after jitter**, so negative jitter can never shorten a provider-safe cooldown.

### Deterministic jitter

The pure policy does not call randomness internally. The scheduler supplies a bounded `jitter_unit` in `[-1, +1]` and the policy applies:

```text
1 + jitter_fraction * jitter_unit
```

This keeps production scheduling de-synchronized while making Gate tests reproducible. With a 10% jitter setting, a 100 s base becomes exactly 90..110 s.

### Creator-state isolation

`PollDecision` contains timing/operational facts only:

```text
delay_s
base_delay_s
minimum_cooldown_s
mode
backoff_step
capped
```

There is deliberately no `status`, `canonical_status`, `live_status`, LiveSession mutation, or notification output.

### Gate 0C-2 acceptance — PASS 15/15

```text
01 HEALTHY uses normal cadence                              PASS
02 DEGRADED uses conservative cadence                       PASS
03 UNAVAILABLE backoff grows exponentially                  PASS
04 backoff is capped                                        PASS
05 RATE_LIMIT enforces minimum cooldown                     PASS
06 AUTH/BLOCKED never tight-loop                            PASS
07 bounded jitter never violates minimum cooldown           PASS
08 deterministic jitter makes decisions reproducible        PASS
09 HEALTHY state resets unavailable backoff                 PASS
10 scheduler exposes no creator live-state output           PASS
11 invalid policy configuration rejected                    PASS
12 identical snapshot inputs produce same decision          PASS
13 STARTING uses separate initial cadence                   PASS
14 jitter remains bounded around non-cooldown base          PASS
15 invalid poll context rejected                            PASS
```

Combined Gate 0C CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007431910
head      66407497413af6b17de047cf5f1bd970eb70a9b2
result    completed / success
syntax    platform_health + poll_policy PASS
suite     34 tests / 34 PASS
```

---

## Gate 0C-3 — Fault-injection recovery — NEXT

0C-3 must prove complete operational sequences, not isolated functions. It should compose `HealthTracker + poll_policy` under deterministic fault scenarios while keeping creator state facts untouched.

Required scenarios:

```text
healthy -> TIMEOUT -> TIMEOUT -> degraded -> recovery
healthy -> NETWORK outage -> unavailable -> recovery probes -> healthy
healthy -> PARSE/schema failure -> degraded/unavailable -> recovery
healthy -> RATE_LIMIT -> cooldown -> later clean recovery
healthy -> AUTH/BLOCKED -> immediate unavailable -> long recovery cooldown
slow decisive LIVE/OFFLINE -> degraded health but decisive creator fact preserved
old delayed failure after newer success -> stale/no regression
mixed scopes: one unavailable + one healthy -> aggregate degraded
```

Acceptance must explicitly verify that no fault sequence fabricates creator OFFLINE or closes a Gate 0B LiveSession through health logic.

---

## Gate 0C-4 — Source-composition policy — NOT STARTED

Freeze how canonical status, corroboration and metadata enrichment interact when one source is degraded/unavailable. Source selection may change; creator truth must still obey the normalized observation contract and `UNKNOWN != OFFLINE`.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C-1  PASS
Gate 0C-2  PASS
Gate 0C-3  NEXT
Gate 0C    IN PROGRESS
Gate 0D    NOT STARTED
Gate 0E    NOT STARTED
```
