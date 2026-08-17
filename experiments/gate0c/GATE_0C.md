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
0C-3 Fault-injection recovery              IN PROGRESS / REAL SOAK NEXT
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

Normalized failures:

```text
TIMEOUT | NETWORK | RATE_LIMIT | PARSE | AUTH | BLOCKED | EMPTY | OTHER
```

`AUTH` and `BLOCKED` are hard health failures and make the route immediately `UNAVAILABLE`. General failures use consecutive-failure hysteresis. A slow decisive response preserves creator LIVE/OFFLINE while health becomes `DEGRADED`.

### Ordering / idempotency

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

### Gate 0C-1 acceptance — PASS 19/19

Clean single-model CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007232769
head      96b8cffe917b51cd41ddaacf281bb9b58ac7fa09
result    completed / success
suite     19 / 19 PASS
```

Intermediate failed runs during duplicate prototype cleanup are superseded by the clean single-model run above and are not semantic Gate failures.

---

## Gate 0C-2 — Poll / retry / backoff policy — PASS

Canonical implementation:

```text
experiments/gate0c/poll_policy.py
experiments/gate0c/test_poll_policy.py
```

The polling policy is pure: it receives health/failure facts and returns only next-poll timing. It performs no HTTP request, mutates no `HealthTracker`, and exposes no creator LIVE/OFFLINE output.

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

These are acceptance parameters, **not production provider SLA/tuning**.

Default unavailable backoff grows:

```text
180 -> 360 -> 720 -> 1440 -> 1800(capped)
```

Negative jitter cannot violate provider-safe minimum cooldown. Positive jitter also cannot escape the generic `UNAVAILABLE` backoff ceiling; an explicitly configured provider-safety minimum cooldown may intentionally be longer than that generic cap.

`PollDecision` contains operational timing facts only:

```text
delay_s
base_delay_s
minimum_cooldown_s
mode
backoff_step
capped
```

### Gate 0C-2 acceptance — PASS 16/16

The suite proves normal/degraded cadence, exponential recovery backoff, ceiling behavior before and after jitter, rate-limit/hard-block cooldowns, deterministic bounded jitter, health-driven reset, creator-state isolation and configuration validation.

Latest strengthened CI evidence:

```text
workflow  Gate 0C Health Smoke
run       32007556548
head      8e8e13c6c413fb17d3f709335a645e4075e01ec9
result    completed / success
```

---

## Gate 0C-3 — Fault-injection recovery — IN PROGRESS

0C-3 is split into deterministic domain/operational fault scenarios and a real StreamGet soak/fault run.

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

Combined CI evidence after the strengthened 0C-2 cap test:

```text
workflow  Gate 0C Health Smoke
run       32007787025
head      4e890e47626f586eedab3c87e15d05ea2ec37961
result    completed / success
suite     45 tests / 45 PASS
```

This proves the deterministic composition boundary:

```text
provider fault -> UNKNOWN + degraded health
provider fault != OFFLINE
provider fault != LiveSession close
```

### B. Real StreamGet soak / forced network fault — NEXT EVIDENCE

Harness:

```text
experiments/gate0c/streamget_soak.py
```

The harness reuses Gate 0A `streamget_status_probe.probe()` **in-process**. It does not use subprocess/stdout transport, avoiding the Windows/Unicode watcher issue previously seen in Gate 0A.

It records normalized JSONL evidence only:

```text
round / profile
status / raw_room_status
error_type / normalized failure_kind
latency
health before / after
consecutive failure streak
poll delay / mode
network-fault injection requested / effective
```

No raw provider payload or cookie value is written.

For selected fault rounds it temporarily points standard proxy variables to `127.0.0.1:1`. If StreamGet ignores those environment variables and still returns a decisive result, the harness records the injection as ineffective/inconclusive rather than fabricating a failure.

Recommended first real run from repository root, no Douyin cookie:

```bash
unset DOUYIN_COOKIE

./.venv-gate0a-streamget/Scripts/python.exe \
  experiments/gate0c/streamget_soak.py \
  "https://www.douyin.com/user/MS4wLjABAAAADlel7zsI5JBe2Uv_FZoX_Ecv8iiK38CXB-3ah_9SJE14892-nxueFDQU71B4FRsz" \
  --rounds 7 \
  --interval 30 \
  --inject-network-failure-rounds 2,3,4,5
```

Expected evidence shape if the proxy fault injection is effective:

```text
round 1      decisive OFFLINE/LIVE -> HEALTHY
round 2      UNKNOWN network fault -> failure streak 1
round 3      UNKNOWN network fault -> DEGRADED
round 4      UNKNOWN network fault -> DEGRADED
round 5      UNKNOWN network fault -> UNAVAILABLE
round 6      clean decisive fact   -> DEGRADED
round 7      clean decisive fact   -> HEALTHY
```

The creator's decisive status may naturally change during the run; Gate 0C-3 only requires that injected/provider failures normalize to UNKNOWN and never manufacture OFFLINE.

Real soak evidence is still required before 0C-3 can close. Therefore Gate 0C overall remains **IN PROGRESS**.

---

## Gate 0C-4 — Source-composition policy — NOT STARTED

After real fault evidence, freeze how canonical StreamGet status, corroborating TikHub/F2 facts, and metadata enrichment interact when one source is degraded/unavailable. Source selection may change, but creator truth must continue to obey `UNKNOWN != OFFLINE`.

## Current progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C-1  PASS
Gate 0C-2  PASS
Gate 0C-3  IN PROGRESS / REAL SOAK NEXT
Gate 0C    IN PROGRESS
Gate 0D    NOT STARTED
Gate 0E    NOT STARTED
```
