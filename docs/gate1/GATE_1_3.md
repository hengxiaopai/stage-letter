# Gate 1.3 — Platform Adapter Framework

Status: **PASS / CLOSED**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)
- [`GATE_1_3_DOUYIN.md`](./GATE_1_3_DOUYIN.md)
- [`GATE_1_3_MULTIPLATFORM.md`](./GATE_1_3_MULTIPLATFORM.md)
- [`GATE_1_3_ACCEPTANCE.md`](./GATE_1_3_ACCEPTANCE.md)

## 1. Final result

```text
Gate 1.3-1  Adapter Contract + Registry Freeze                    PASS
Gate 1.3-2  Provider Error / Ambiguity Normalization              PASS
Gate 1.3-3  Douyin Formal Adapter Migration                       PASS / CLOSED
Gate 1.3-4  Bilibili / Huya / Douyu Formal Adapter Migration      PASS / CLOSED
Gate 1.3-5  Adapter Regression / Acceptance                       PASS / CLOSED
Gate 1.3    PASS / CLOSED
```

Final user-local evidence on 2026-08-19:

```text
Gate 1.3 final acceptance contracts   10 / 10 PASS
complete Gate 1 suite                235 / 235 PASS
```

## 2. Accepted provider controls

```text
Douyin     LIVE PASS / OFFLINE PASS
Bilibili   LIVE PASS / corrected OFFLINE PASS
Huya       LIVE PASS / OFFLINE PASS
Douyu      LIVE PASS / OFFLINE PASS
```

No additional provider run is required solely because Gate 1.3 closed; future provider re-probing is evidence-driven when a transport or semantic changes.

## 3. Frozen platform truth

```text
formal LiveStatus = LIVE / OFFLINE / UNKNOWN only

Douyin:    2 -> LIVE, 4 -> OFFLINE, other/failure -> UNKNOWN
Bilibili:  1 -> LIVE, 0/2 -> OFFLINE for creator-live truth,
           replay/roundStatus alone never promotes LIVE
Huya:      2/liveStatus-on -> LIVE, 1/liveStatus-off -> OFFLINE,
           0/3/conflict/failure -> UNKNOWN
Douyu:     show_status 1 -> LIVE, 2 -> OFFLINE,
           0/3/4/conflict/failure -> UNKNOWN,
           videoLoop/replay alone is not creator-live truth
```

Provider metadata remains non-canonical and never overrides explicit live-state evidence.

## 4. Cross-platform registry

The formal registry contains exactly:

```text
bilibili
douyin
douyu
huya
```

It uses only formal adapters, performs no provider I/O during construction, does not eagerly import StreamGet, and owns no LiveSession/LiveEvent/notification rules.

## 5. Legacy treatment

The top-level `platform_adapters/*` package remains quarantined legacy migration debt. Formal `stage_letter/*` does not import it as a runtime dependency.

## 6. Inherited status

```text
Gate 0A    DEGRADED / deferred same-creator lifecycle evidence gap
Gate 0B-E  PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   PASS / CLOSED
Gate 1.4   CURRENT
```

Gate 0A remains DEGRADED and is not rewritten by Gate 1.3 success.

## 7. Exit

Gate 1.3 exits into **Gate 1.4 — Monitoring Scheduler + Observation Pipeline**. The first Gate 1.4 slice must discover explicitly enabled monitoring targets deterministically before introducing scheduler cadence, provider polling, or observation persistence orchestration.
