# Gate 1.3 — Platform Adapter Framework

Status: **CURRENT / 1.3-1 PASS / 1.3-2 PASS / 1.3-3 PASS / 1.3-4 CURRENT**

Entry authority: Gate 1.2 PASS / CLOSED.

Primary freezes:

- [`GATE_1_3_ADAPTER_CONTRACT.md`](./GATE_1_3_ADAPTER_CONTRACT.md)
- [`GATE_1_3_FAILURE_NORMALIZATION.md`](./GATE_1_3_FAILURE_NORMALIZATION.md)
- [`GATE_1_3_DOUYIN.md`](./GATE_1_3_DOUYIN.md)
- [`GATE_1_3_MULTIPLATFORM.md`](./GATE_1_3_MULTIPLATFORM.md)

## 1. Goal

Gate 1.3 introduces the formal platform-adapter boundary that converts external provider responses into normalized Stage Letter facts without allowing provider vocabulary or transport failures to become canonical domain truth.

Adapters emit normalized facts only. They do not persist canonical LiveSession/LiveEvent truth or decide notification eligibility.

## 2. Gate 1.3 slices

```text
Gate 1.3-1  Adapter Contract + Registry Freeze
Gate 1.3-2  Provider Error / Ambiguity Normalization
Gate 1.3-3  Douyin Formal Adapter Migration
Gate 1.3-4  Bilibili / Huya / Douyu Formal Adapter Migration
Gate 1.3-5  Adapter Regression / Acceptance
```

## 3. Accepted slices

```text
Gate 1.3-1  PASS
Gate 1.3-2  PASS
Gate 1.3-3  PASS / CLOSED
```

Gate 1.3-3 accepted evidence includes 12/12 Douyin adapter, 10/10 StreamGet gateway, 3/3 probe CLI, 157/157 complete Gate 1, and real LIVE/OFFLINE provider controls. Gate 0A remains DEGRADED for its deferred lifecycle evidence gap.

## 4. Gate 1.3-4 — CURRENT

```text
Gate 1.3-4A  Bilibili  PASS / CLOSED
Gate 1.3-4B  Huya      PASS / CLOSED
Gate 1.3-4C  Douyu     PASS / CLOSED
Gate 1.3-4D  cross-platform acceptance CURRENT
```

Accepted Bilibili evidence: 11/11 formal adapter, 9/9 HTTP gateway, 177/177 complete Gate 1, plus current LIVE and corrected OFFLINE provider controls. Replay/carousel is not creator LIVE.

Accepted Huya evidence: 10/10 formal adapter, 10/10 HTTP gateway, 197/197 complete Gate 1, plus current LIVE/OFFLINE provider controls. Formal mapping remains `2/liveStatus-on -> LIVE`, `1/liveStatus-off -> OFFLINE`, `0/3/other -> UNKNOWN`, failure/conflict -> UNKNOWN.

Accepted Douyu evidence: 10/10 formal adapter, 10/10 HTTP gateway, 217/217 complete Gate 1, plus current LIVE/OFFLINE provider controls. Formal mapping remains `show_status 1 -> LIVE`, `show_status 2 -> OFFLINE`, `0/3/4/other -> UNKNOWN`, failure -> UNKNOWN. Replay/loop activity and list absence are not canonical creator-live truth.

### Gate 1.3-4D cross-platform registry acceptance — current

Landed:

```text
stage_letter/infrastructure/platforms/factory.py
tests/gate1/test_platform_registry_acceptance.py
stage_letter/infrastructure/platforms/__init__.py
```

`build_formal_adapter_registry()` wires exactly:

```text
bilibili -> BilibiliFormalAdapter(BilibiliHttpGateway)
douyin   -> DouyinFormalAdapter(StreamGetDouyinGateway)
douyu    -> DouyuFormalAdapter(DouyuHttpGateway)
huya     -> HuyaFormalAdapter(HuyaHttpGateway)
```

The registry is freshly constructed, explicit, and infrastructure-owned. Construction performs no provider request; StreamGet remains lazy and is not required during registry construction.

Eight acceptance contracts verify the exact platform set, structural `LivePlatformAdapter` compatibility, key/platform agreement, formal concrete adapter types, no eager StreamGet import, fresh instances per build, explicit unknown-platform errors, and no legacy/session/event/notification ownership.

The accepted entering baseline is 217 tests, so Gate 1.3-4D expects:

```text
8 / 8 platform registry acceptance contracts
225 / 225 complete Gate 1 suite
```

No further provider probes are required for this slice if those deterministic regressions remain green.

## 5. Legacy treatment

The existing top-level `platform_adapters/*` package remains legacy migration debt. Formal `stage_letter/*` does not import it.

## 6. Preserved inherited status

```text
Gate 0A    DEGRADED / deferred lifecycle evidence gap
Gate 0B-E  PASS
Gate 1.0   PASS
Gate 1.1   PASS
Gate 1.2   PASS / CLOSED
Gate 1.3   CURRENT
```

## 7. Current progression

```text
Gate 1.3-1   PASS
Gate 1.3-2   PASS
Gate 1.3-3   PASS / CLOSED
Gate 1.3-4A  PASS / CLOSED
Gate 1.3-4B  PASS / CLOSED
Gate 1.3-4C  PASS / CLOSED
Gate 1.3-4D  CURRENT / formal four-platform registry + 8 acceptance contracts landed
Gate 1.3-5   NOT STARTED
Gate 1.3     CURRENT
```

## 8. Stop rules

Stop with FAIL/BLOCKED if progress requires legacy runtime imports, failure/ambiguity -> OFFLINE, replay/list absence -> LIVE/OFFLINE truth, fabricated provider identity, provider I/O during registry construction, eager StreamGet loading, or adapter ownership of sessions/events/notifications.
