# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 PASS / 1.3-2 PASS / 1.3-3 PASS / 1.3-4 PASS / 1.3-5 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)
- [`GATE_1_3_DOUYIN.md`](./GATE_1_3_DOUYIN.md)
- [`GATE_1_3_MULTIPLATFORM.md`](./GATE_1_3_MULTIPLATFORM.md)
- [`GATE_1_3_ACCEPTANCE.md`](./GATE_1_3_ACCEPTANCE.md)

## 1. Goal

Gate 1.3 introduces the formal platform-adapter boundary that converts external provider responses into normalized Stage Letter facts without allowing provider vocabulary, weak metadata, or transport failures to become canonical live-state truth.

Adapters emit normalized facts only. They do not persist canonical LiveSession/LiveEvent truth or decide notification eligibility.

## 2. Gate 1.3 slices

```text
Gate 1.3-1  Adapter Contract + Registry Freeze                    PASS
Gate 1.3-2  Provider Error / Ambiguity Normalization              PASS
Gate 1.3-3  Douyin Formal Adapter Migration                       PASS / CLOSED
Gate 1.3-4  Bilibili / Huya / Douyu Formal Adapter Migration      PASS / CLOSED
Gate 1.3-5  Adapter Regression / Acceptance                       CURRENT
```

## 3. Accepted evidence entering Gate 1.3-5

### Douyin

```text
formal adapter contracts        12 / 12 PASS
StreamGet gateway contracts     10 / 10 PASS
provider-probe CLI contracts     3 / 3 PASS
complete Gate 1 suite          157 / 157 PASS
real LIVE provider control           PASS
real OFFLINE provider control        PASS
```

Formal mapping remains integer `2 -> LIVE`, integer `4 -> OFFLINE`, all other/failure outcomes -> UNKNOWN.

### Bilibili

```text
formal adapter contracts        11 / 11 PASS
HTTP gateway contracts           9 / 9 PASS
complete Gate 1 suite          177 / 177 PASS
provider LIVE control                PASS
corrected provider OFFLINE control   PASS
```

Current provider evidence corrected replay/carousel semantics: actual creator live status `1 -> LIVE`; `0 -> OFFLINE`; carousel/replay status `2 -> OFFLINE` for creator-live truth; `roundStatus` alone never promotes LIVE.

### Huya

```text
formal adapter contracts        10 / 10 PASS
HTTP gateway contracts          10 / 10 PASS
complete Gate 1 suite          197 / 197 PASS
provider LIVE control                PASS
provider OFFLINE control             PASS
```

Formal mapping remains `2/liveStatus-on -> LIVE`, `1/liveStatus-off -> OFFLINE`, `0/3/other/conflict/failure -> UNKNOWN`. Room id is the proven monitor key; title metadata is non-canonical.

### Douyu

```text
formal adapter contracts        10 / 10 PASS
HTTP gateway contracts          10 / 10 PASS
complete Gate 1 suite          217 / 217 PASS
provider LIVE control                PASS
provider OFFLINE control             PASS
```

Formal mapping remains `show_status 1 -> LIVE`, `show_status 2 -> OFFLINE`, `0/3/4/other/failure -> UNKNOWN`. `videoLoop`/replay and list absence are not creator-live truth.

### Cross-platform registry

```text
registry acceptance contracts    8 / 8 PASS
complete Gate 1 suite          225 / 225 PASS
```

The formal registry contains exactly `bilibili`, `douyin`, `douyu`, and `huya`, uses only formal adapter implementations, performs no provider I/O during construction, and does not eagerly require StreamGet.

Result: **Gate 1.3-4 PASS / CLOSED**.

## 4. Gate 1.3-5 — CURRENT

Landed:

```text
tests/gate1/test_gate13_acceptance.py       10 tests
docs/gate1/GATE_1_3_ACCEPTANCE.md
```

The final deterministic contracts verify:

```text
formal LiveStatus remains exactly LIVE/OFFLINE/UNKNOWN
formal platform set remains exactly four platforms
public platform package exports all four formal adapters/gateways + registry factory
per-platform evidence-backed mapping tables stay frozen and disjoint
registry key matches adapter.platform and all entries implement LivePlatformAdapter
factory performs no provider I/O and owns no session/event/notification rules
formal platform runtime imports no legacy platform_adapters/experiments/core/api/workers
Bilibili replay/roundStatus cannot promote creator LIVE
Douyu videoLoop alone cannot promote creator LIVE
Huya/Douyu conflicting explicit provider evidence remains non-decisive
```

The accepted entering baseline is 225 tests. With ten final acceptance contracts, expected local evidence is:

```text
10 / 10 Gate 1.3 final acceptance contracts
235 / 235 complete Gate 1 suite
```

No new provider probe is required merely to close Gate 1.3, because decisive LIVE/OFFLINE provider controls were already accepted per platform.

## 5. Legacy treatment

The top-level `platform_adapters/*` package remains legacy migration debt. Formal `stage_letter/*` does not import it as a runtime dependency.

## 6. Preserved inherited status

```text
Gate 0A    DEGRADED / deferred same-creator lifecycle evidence gap
Gate 0B-E  PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   CURRENT
```

Gate 0A remains DEGRADED and is not rewritten by Gate 1.3 provider success.

## 7. Current progression

```text
Gate 1.3-1   PASS
Gate 1.3-2   PASS
Gate 1.3-3   PASS / CLOSED
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  PASS / CLOSED
Gate 1.3-4C  PASS / CLOSED
Gate 1.3-4D  PASS / CLOSED
Gate 1.3-4   PASS / CLOSED
Gate 1.3-5   CURRENT / 10 final acceptance contracts landed; local evidence pending
Gate 1.3     CURRENT
```

## 8. Exit condition

If `10/10 + 235/235` pass locally, close as:

```text
Gate 1.3-5  PASS / CLOSED
Gate 1.3    PASS / CLOSED
Gate 1.4    CURRENT
```

## 9. Stop rules

Stop with FAIL/BLOCKED if progress requires legacy runtime imports, failure/ambiguity -> OFFLINE, replay/list absence -> creator LIVE/OFFLINE truth, fabricated provider identity, provider I/O during registry construction, eager StreamGet loading, or adapter ownership of sessions/events/notifications.
