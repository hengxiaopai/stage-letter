# Gate 1.1-6 — Gate 0 Regression + Golden Path Comparison

Status: **PASS**

## Purpose

Gate 1.1-6 closes the Domain Model + PostgreSQL Schema gate by proving that the
formal Gate 1 domain/persistence work has not drifted from the accepted Gate 0
semantics.

This slice does **not** claim that the formal Gate 1 runtime pipeline is already
implemented end to end. State-engine, source-composition, notification runtime,
and adapter/service migrations occur in later Gate 1 slices. Gate 1.1-6 proves
that the new formal vocabulary and persistence boundaries remain compatible
with the accepted Gate 0 behavioral oracle.

## Accepted Gate 0 oracle suites

Deterministic suites retained in the repository:

```text
Gate 0B  state engine + persistent state        37 tests
Gate 0C  health + polling + source composition  65 tests
Gate 0D  notification truth + provider/retry    54 tests
Gate 0E  composed golden path                   15 tests
```

Gate 0E composes the accepted pipeline:

```text
SourceObservation
-> SourceComposer
-> LiveObservation
-> PersistentStateEngine
-> LiveSession / LiveEvent
-> notification eligibility
-> logical NotificationDelivery
-> DeliveryRetryMachine
-> normalized provider result
```

The regression probe runs only deterministic local tests. It does not repeat
real WeChat sends, provider calls, or Gate 0A lifecycle observation.

## Formal semantic comparison

`tests/gate1/test_gate0_regression_contract.py` reads the accepted Gate 0 oracle
source as test evidence and compares it to formal Gate 1 enums/contracts.

Required parity:

```text
Gate 0B ObservationStatus == Gate 1 LiveStatus
Gate 0C CanonicalStatus   == Gate 1 LiveStatus
Gate 0B SessionOrigin     == Gate 1 SessionOrigin
Gate 0B LiveEventType     == Gate 1 LiveEventType
Gate 0B LiveEventCause    == Gate 1 LiveEventCause
Gate 0D Channel           == Gate 1 DeliveryChannel
Gate 0D GrantState        == Gate 1 GrantState
Gate 0D ExecutionState    == Gate 1 DeliveryState
Gate 0C HealthState       == Gate 1 RuntimeHealthState
```

The same test file also proves that formal runtime code under `stage_letter/`
does not import `experiments/*`.

This preserves the architecture rule:

```text
experiments/* = oracle/evidence only
stage_letter/* = formal runtime
```

## Regression probe

`scripts/gate1_regression_probe.py` executes each accepted deterministic oracle
suite in an isolated subprocess working directory, then runs the formal Gate 1
contract suite with the same project Python interpreter.

Minimum accepted suite counts:

```text
Gate 0B >= 37
Gate 0C >= 65
Gate 0D >= 54
Gate 0E >= 15
Gate 1  >= 55
```

The Gate 1 minimum includes the Gate 0 parity/runtime-boundary tests.

## Accepted evidence

The operator confirmed on 2026-08-19 that the Gate 1.1-6 regression evidence
passed and progression to Gate 1.2 was authorized. No exact test counts are
invented here beyond the minimums encoded by the checked-in probe.

Accepted conclusions:

```text
A. Gate 0B deterministic oracle remains green                 PASS
B. Gate 0C deterministic oracle remains green                 PASS
C. Gate 0D deterministic oracle remains green                 PASS
D. Gate 0E golden-path oracle remains green                   PASS
E. Gate 1 formal contract suite remains green                 PASS
F. Gate 0 -> Gate 1 enum/semantic parity tests pass           PASS
G. formal stage_letter runtime has no experiments imports     PASS
H. Gate 0A DEGRADED inherited gap remains explicitly recorded PASS
I. no new real-provider exactly-once claim is introduced      PASS
```

## Preserved non-regression boundaries

Gate 1.1 remains compatible with these accepted conclusions:

```text
UNKNOWN != OFFLINE
BOOTSTRAP_LIVE != TRANSITION
source/provider health never rewrites canonical live truth
one PlatformAccount has at most one open LiveSession
logical delivery identity = (user_id, live_event_id, channel)
IN_FLIGHT is persisted before external send
crash-after-send/before-response -> AMBIGUOUS
AMBIGUOUS -> no blind resend
SENT is terminal for one logical delivery only
SENT does not prove global grant exhaustion
notification/provider failure does not mutate creator live truth
```

## Gate 0A inherited status

Gate 0A remains:

```text
DEGRADED / progression allowed with known lifecycle evidence gap
```

Gate 1.1-6 does not rerun or fabricate the deferred real OFFLINE -> LIVE ->
OFFLINE lifecycle evidence and does not convert Gate 0A to PASS.

## Result

```text
Gate 1.1-6  PASS
Gate 1.1    eligible to close PASS
Gate 1.2    progression allowed
```
