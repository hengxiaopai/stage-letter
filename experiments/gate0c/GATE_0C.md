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
0C-3 Fault-injection recovery              PASS
0C-4 Source-composition policy             CURRENT
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

Normalized failures:

```text
TIMEOUT | NETWORK | RATE_LIMIT | PARSE | AUTH | BLOCKED | EMPTY | OTHER
```

`AUTH` and `BLOCKED` are hard health failures and make the route immediately `UNAVAILABLE`. General failures use consecutive-failure hysteresis. A slow decisive response preserves creator LIVE/OFFLINE while health becomes `DEGRADED`.

Health ordering uses probe `started_at`:

```text
duplicate sample_id -> DUPLICATE / no health mutation
started_at < watermark -> STALE / no streak or health mutation
started_at == watermark -> not automatically stale
```

`HealthSnapshot` / `HealthTracker.from_snapshot()` preserve health state, streaks, watermark, sample-id idempotency and diagnostics across a persistence boundary.

Partial-platform aggregation is conservative:

```text
all HEALTHY      -> HEALTHY
all UNAVAILABLE  -> UNAVAILABLE
all STARTING     -> STARTING
mixed scopes     -> DEGRADED
```

Acceptance: **PASS 19/19**.

Clean CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007232769
head      96b8cffe917b51cd41ddaacf281bb9b58ac7fa09
result    completed / success
suite     19 / 19 PASS
```

---

## Gate 0C-2 — Poll / retry / backoff policy — PASS

Canonical implementation:

```text
experiments/gate0c/poll_policy.py
experiments/gate0c/test_poll_policy.py
```

The polling policy is pure: it receives health/failure facts and returns only next-poll timing. It performs no HTTP request, mutates no `HealthTracker`, and exposes no creator LIVE/OFFLINE output.

Gate timing defaults:

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

These are acceptance parameters, **not production provider SLA/tuning**.

Default unavailable backoff grows:

```text
180 -> 360 -> 720 -> 1440 -> 1800(capped)
```

Negative jitter cannot violate provider-safe minimum cooldown. Positive jitter cannot escape the generic `UNAVAILABLE` backoff ceiling; an explicitly configured provider-safety minimum cooldown may intentionally be longer than that generic cap.

`PollDecision` contains operational timing facts only:

```text
delay_s
base_delay_s
minimum_cooldown_s
mode
backoff_step
capped
```

Acceptance: **PASS 16/16**.

Latest strengthened CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007556548
head      8e8e13c6c413fb17d3f709335a645e4075e01ec9
result    completed / success
```

---

## Gate 0C-3 — Fault-injection recovery — PASS

0C-3 combines deterministic fault composition with a real StreamGet forced-network-fault soak.

### A. Deterministic fault composition — PASS 10/10

Canonical harness/tests:

```text
experiments/gate0c/fault_recovery.py
experiments/gate0c/test_fault_recovery.py
```

Validated scenarios:

```text
01 healthy -> TIMEOUT x2 -> DEGRADED -> two clean samples -> HEALTHY       PASS
02 NETWORK x4 -> UNAVAILABLE -> recovery probes -> HEALTHY                 PASS
03 PARSE failures never become creator OFFLINE                             PASS
04 RATE_LIMIT enforces cooldown while creator fact remains UNKNOWN         PASS
05 AUTH/BLOCKED -> immediate UNAVAILABLE + long cooldown                    PASS
06 slow decisive LIVE is preserved while health becomes DEGRADED           PASS
07 older delayed failure after newer success -> STALE / no regression       PASS
08 healthy + unavailable scopes aggregate to DEGRADED                       PASS
09 provider UNKNOWN faults cannot close an open Gate 0B LiveSession         PASS
10 clean LIVE after fault period keeps the same Gate 0B LiveSession         PASS
```

### B. Real StreamGet forced-network-fault soak — PASS

Evidence summary:

```text
profile: X.四五六🍉
rounds: 7
forced fault rounds: 2,3,4,5
cookie: not configured
```

Observed sequence:

```text
round 1  OFFLINE raw=4    -> HEALTHY
round 2  UNKNOWN          -> HEALTHY      failure streak 1
round 3  UNKNOWN          -> DEGRADED     failure streak 2
round 4  UNKNOWN          -> DEGRADED     failure streak 3
round 5  UNKNOWN          -> UNAVAILABLE  failure streak 4
round 6  OFFLINE raw=4    -> DEGRADED     clean recovery #1
round 7  OFFLINE raw=4    -> HEALTHY      clean recovery #2
```

Measured latencies were 4371, 2976, 2999, 3018, 2985, 3360 and 3642 ms respectively.

Final harness facts:

```text
samples                     7
injection_requested         4
injection_effective         4
unknown                     4
offline                     3
false_offline_from_failure  0
final_health                HEALTHY
fault_injection_conclusive  true
```

This closes the real operational safety proof:

```text
provider/network fault -> UNKNOWN + source-health degradation
provider/network fault != OFFLINE
provider/network fault != LiveSession close
clean recovery requires hysteresis before HEALTHY
```

Normalized evidence record:

```text
experiments/gate0c/REAL_SOAK_20260817.md
```

The local JSONL path reported by the harness was `experiments/gate0c/data/streamget-soak-20260817-162348.jsonl`; the raw JSONL is not committed as canonical repository evidence.

Latest Gate 0C smoke before real soak evidence capture remained green:

```text
workflow  Gate 0C Health Smoke
run       32007897530
head      6b40374e9243a49f27c95692ee19f76ac73d8c3b
result    completed / success
```

---

## Gate 0C-4 — Source-composition policy — CURRENT

0C-4 freezes how multiple sources contribute truth without allowing one provider failure to corrupt canonical creator state.

Current candidate composition from Gate 0A/0C evidence:

```text
PlatformAccount stable identity (uid/sec_uid/douyin_id)
    |
    +-- StreamGet PROFILE
    |      primary canonical status candidate
    |      explicit 2 -> LIVE
    |      explicit 4 -> OFFLINE
    |      failure/ambiguity -> UNKNOWN
    |
    +-- TikHub / F2 while LIVE
           corroboration and metadata enrichment
           room_id when available
           never allowed to force OFFLINE merely because data is absent
```

0C-4 must freeze at least these rules:

```text
1. status authority vs metadata authority are separate concerns
2. a source health state never directly rewrites creator LIVE/OFFLINE
3. absent/null metadata is not an OFFLINE signal
4. corroborating sources may strengthen confidence but cannot override a newer decisive canonical fact without an explicit arbitration rule
5. source disagreement must degrade confidence / surface UNKNOWN or conflict state rather than silently choose the more convenient answer
6. metadata enrichment may fail independently while canonical status remains valid
7. room_id/title/live_url/source_started_at carry provenance
8. bootstrap LIVE remains distinct from a proven OFFLINE -> LIVE transition
9. no source can close a LiveSession on UNKNOWN
10. failover/source switching must preserve observation ordering and idempotency
```

0C-4 acceptance should be deterministic and provider-agnostic. Production authorization/compliance remains outside this semantic Gate and is still unresolved.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C-1  PASS
Gate 0C-2  PASS
Gate 0C-3  PASS
Gate 0C-4  CURRENT
Gate 0C    IN PROGRESS
Gate 0D    NOT STARTED
Gate 0E    NOT STARTED
```
