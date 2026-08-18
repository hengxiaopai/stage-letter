# Gate 0C — Stability + Platform Health

Status: **PASS**

## Scope

Gate 0C validates operational stability around normalized live-status probes before they reach Gate 0B canonical state handling.

Frozen boundary:

```text
provider/source failure
    -> source health may degrade
    -> creator observation may normalize to UNKNOWN
    -> MUST NOT become OFFLINE merely because the source is unhealthy
```

Gate 0B remains the owner of canonical LiveSession behavior.

## Final result

```text
0C-1 Platform / Provider Health Policy     PASS 19/19
0C-2 Poll / retry / backoff policy         PASS 16/16
0C-3 Fault-injection recovery              PASS 10/10 + real soak PASS
0C-4 Source-composition policy             PASS 20/20
```

A clean local full-suite acceptance run on 2026-08-18 produced:

```text
Ran 65 tests in 0.022s
OK
```

## 0C-1 — Health policy

Health is independent from creator truth:

```text
HealthState: STARTING | HEALTHY | DEGRADED | UNAVAILABLE
CanonicalStatus: LIVE | OFFLINE | UNKNOWN
```

The suite proves hysteresis, hard AUTH/BLOCKED failure behavior, slow-response degradation without status rewriting, delayed/stale protection, restart snapshots, and conservative multi-scope aggregation.

## 0C-2 — Poll / retry / backoff

The scheduling policy is pure and emits timing facts only. Gate acceptance defaults are configurable, not production SLA values:

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

It proves exponential recovery backoff, hard ceiling, provider-safe cooldowns, deterministic jitter, and creator-state isolation.

## 0C-3 — Fault recovery

Deterministic composition proves TIMEOUT, NETWORK, PARSE, RATE_LIMIT, AUTH/BLOCKED, slow decisive responses, delayed stale failures, mixed-scope health, and that provider UNKNOWN cannot close an open Gate 0B LiveSession.

Real StreamGet forced-network-fault evidence on X.四五六🍉 produced:

```text
round 1  OFFLINE -> HEALTHY
round 2  UNKNOWN -> HEALTHY      failure 1
round 3  UNKNOWN -> DEGRADED     failure 2
round 4  UNKNOWN -> DEGRADED     failure 3
round 5  UNKNOWN -> UNAVAILABLE  failure 4
round 6  OFFLINE -> DEGRADED     recovery 1
round 7  OFFLINE -> HEALTHY      recovery 2
```

Final facts: four requested injections, four effective injections, four UNKNOWNs, zero false OFFLINEs from failures, final health HEALTHY. Canonical evidence is recorded in `experiments/gate0c/REAL_SOAK_20260817.md`.

## 0C-4 — Source composition

Current candidate deployment mapping:

```text
StreamGet PROFILE -> PRIMARY_STATUS
TikHub            -> POSITIVE_STATUS + metadata enrichment
F2                -> POSITIVE_STATUS + metadata enrichment
```

Frozen rules include:

```text
status authority != metadata authority
null metadata != OFFLINE
positive-only sources cannot create OFFLINE
recent contradictory authorized claims -> CONFLICT -> UNKNOWN
UNKNOWN / CONFLICT cannot close LiveSession
metadata fields carry source provenance
ordering/idempotency survive restart
```

The 20/20 source-composition suite is documented in `experiments/gate0c/SOURCE_COMPOSITION.md`.

## Evidence summary

```text
Gate 0C Health Smoke run 32007232769  health model PASS
Gate 0C Health Smoke run 32007556548  poll policy PASS
Gate 0C Health Smoke run 32007897530  fault composition PASS
Real StreamGet soak                    PASS
Local full suite                       65/65 PASS
```

Production authorization/compliance remains unresolved and is not silently waived by Gate 0C.

## Progression

```text
Gate 0A    DEGRADED / progression allowed with known lifecycle evidence gap
Gate 0B    PASS
Gate 0C    PASS
Gate 0D    START
Gate 0E    NOT STARTED
```
