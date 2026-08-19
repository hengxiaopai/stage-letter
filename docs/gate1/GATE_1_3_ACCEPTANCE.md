# Gate 1.3 — Adapter Framework Final Acceptance

Status: **CURRENT / 1.3-4 PASS / 1.3-5 ACCEPTANCE CONTRACTS LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.3-4A/B/C/D PASS / CLOSED.

## 1. Goal

Gate 1.3-5 is the final deterministic acceptance slice for the formal platform-adapter framework. It does not repeat provider probing already accepted in earlier slices. It verifies that the four formal platforms remain wired through one conservative, infrastructure-owned boundary without reintroducing legacy runtime dependencies or provider-specific state leakage into the formal domain.

## 2. Accepted provider evidence entering 1.3-5

```text
Douyin     real LIVE control     PASS
Douyin     real OFFLINE control  PASS
Bilibili   real LIVE control     PASS
Bilibili   corrected OFFLINE     PASS
Huya       real LIVE control     PASS
Huya       real OFFLINE control  PASS
Douyu      real LIVE control     PASS
Douyu      real OFFLINE control  PASS
```

The provider controls are not re-run in 1.3-5 unless a deterministic regression shows that a platform semantic or transport boundary changed materially.

## 3. Frozen formal truth

```text
formal LiveStatus = LIVE / OFFLINE / UNKNOWN only

Douyin:
  2 -> LIVE
  4 -> OFFLINE
  other/failure -> UNKNOWN

Bilibili creator-live:
  1 -> LIVE
  0 -> OFFLINE
  2 carousel/replay -> OFFLINE for creator-live truth
  roundStatus alone never promotes LIVE
  other/failure -> UNKNOWN

Huya:
  2 / liveStatus-on -> LIVE
  1 / liveStatus-off -> OFFLINE
  0 / 3 / conflict / failure -> UNKNOWN

Douyu:
  show_status 1 -> LIVE
  show_status 2 -> OFFLINE
  0 / 3 / 4 / conflict / failure -> UNKNOWN
  videoLoop/replay alone is not creator-live truth
```

Provider metadata such as stale page titles, room metadata, replay content, or historical room fields never overrides explicit live-state evidence.

## 4. Final acceptance contracts landed

```text
tests/gate1/test_gate13_acceptance.py  10 tests
```

The contracts verify:

```text
formal LiveStatus remains exactly three-state
formal platform set remains exactly bilibili/douyin/douyu/huya
public platform package exports all four formal adapters/gateways + registry factory
per-platform evidence-backed mapping tables remain frozen
LIVE/OFFLINE mapping sets remain disjoint
registry entries implement LivePlatformAdapter and key == adapter.platform
factory performs no provider I/O and owns no session/event/notification rules
formal platform runtime imports no legacy platform_adapters/experiments/core/api/workers
Bilibili roundStatus/replay cannot promote creator LIVE
Douyu videoLoop alone cannot promote creator LIVE
Huya/Douyu conflicting explicit status evidence remains non-decisive
```

## 5. Expected local evidence

Accepted complete Gate 1 baseline entering 1.3-5 is:

```text
225 / 225 PASS
```

The ten final acceptance contracts raise the expected complete Gate 1 suite to:

```text
10 / 10 Gate 1.3 final acceptance contracts
235 / 235 complete Gate 1 suite
```

These are user-local deterministic tests. They are not a claim of CI execution or a new provider-network run.

## 6. Acceptance

```text
A. Gate 1.3-4A Bilibili PASS / CLOSED              PASS
B. Gate 1.3-4B Huya PASS / CLOSED                  PASS
C. Gate 1.3-4C Douyu PASS / CLOSED                 PASS
D. Gate 1.3-4D registry acceptance PASS / CLOSED   PASS
E. exact four-platform formal registry             PASS / CONTRACT
F. evidence-backed state mappings preserved        PASS / CONTRACT
G. UNKNOWN/failure conservatism preserved          PASS / CONTRACT
H. replay/loop cannot fabricate creator LIVE       PASS / CONTRACT
I. no legacy runtime dependency                    PASS / CONTRACT
J. no session/event/notification ownership         PASS / CONTRACT
K. dedicated Gate 1.3 acceptance tests             PENDING / 10
L. complete Gate 1 suite                           PENDING / expected 235
```

Gate 1.3 remains CURRENT until K-L pass.

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the separate deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.3 acceptance must not rewrite that historical status.

## 8. Exit

If 10/10 and 235/235 pass, Gate 1.3 may close as:

```text
Gate 1.3-5  PASS / CLOSED
Gate 1.3    PASS / CLOSED
Gate 1.4    CURRENT
```

No additional real provider controls are required merely to close Gate 1.3, because each platform's decisive LIVE/OFFLINE provider evidence was already accepted in its platform slice.
