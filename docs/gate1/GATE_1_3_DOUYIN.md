# Gate 1.3-3 — Douyin Formal Adapter Migration

Status: **CURRENT / FORMAL ADAPTER CORE LANDED / LOCAL CONTRACT EVIDENCE PENDING**

Entry authority: Gate 1.3-2 PASS / CLOSED.

## 1. Evidence authority

Gate 1.3-3 migrates only Douyin semantics already established by Gate 0A evidence.
It does not infer new provider truth from the legacy top-level adapter.

Accepted Gate 0A StreamGet PROFILE/sec_uid evidence established:

```text
raw_room_status = 2 -> LIVE
raw_room_status = 4 -> OFFLINE
anything else / request failure / parse failure -> UNKNOWN
PROFILE/sec_uid repeated LIVE stability    PASS 3/3
PROFILE/sec_uid repeated OFFLINE stability PASS 3/3
initial multi-creator validation           PASS 6/6
failure safety                             PASS
```

Gate 0A also established that stale room titles and historical live-room URLs are
not canonical state or identity evidence. Stable profile/sec_uid identity remains
the monitoring key.

The inherited Gate 0A lifecycle gap remains **DEGRADED / DEFERRED**. Gate 1.3-3
must not reinterpret the migration as proof of a real same-creator
OFFLINE -> LIVE -> OFFLINE lifecycle.

## 2. Formal implementation

Landed:

```text
stage_letter/infrastructure/platforms/douyin.py
tests/gate1/test_douyin_formal_adapter.py
```

`DouyinFormalAdapter` implements the application-owned `LivePlatformAdapter`
contract and consumes provider transport through an injected
`DouyinProviderGateway` protocol.

The formal package does not import:

```text
platform_adapters/*
experiments/*
core/*
api/*
workers/*
```

This avoids making the legacy Gate 0 implementation a runtime dependency.

## 3. Provider transport seam

The provider gateway exposes only provider records:

```text
resolve_identity(input) -> DouyinIdentityRecord
fetch_profile(sec_uid)  -> DouyinProfileRecord
fetch_live(sec_uid)     -> DouyinLiveRecord
```

A concrete transport may later use StreamGet or another evidence-backed source.
Transport/request/parse/auth failures must be represented through the accepted
Gate 1.3-2 `ProviderOperationError` / `ProviderFailure` vocabulary rather than by
inventing an OFFLINE result.

The gateway does not generate Stage Letter creator/account ids and does not own
persistence, scheduling, state transitions, sessions, events, or notifications.

## 4. Douyin status mapping

The only accepted generic Douyin state mapping in this slice is:

```text
2 -> LIVE
4 -> OFFLINE
all other values -> UNKNOWN
```

String lookalikes such as `"2"` / `"4"` are not promoted automatically. Schema
changes or type drift therefore fail conservatively to UNKNOWN until explicit
evidence justifies a new mapping.

## 5. Stable identity and metadata rules

The formal account identity is `PlatformAccount.platform_user_id`, carrying the
stable Douyin sec_uid/profile identity established by Gate 0A.

Rules:

```text
provider sec_uid mismatch -> UNKNOWN for live reads
provider sec_uid mismatch -> explicit operation error for profile reads
historical room_id may be retained as metadata
canonical_url comes from the stable PlatformAccount identity URL
title may be stale and never overrides status
source_started_at is accepted only for explicit LIVE
OFFLINE / UNKNOWN never inherit a source start time
```

## 6. Failure behavior

```text
ProviderOperationError -> UNKNOWN live snapshot
TimeoutError            -> UNKNOWN live snapshot
ConnectionError         -> UNKNOWN live snapshot
identity mismatch       -> UNKNOWN live snapshot
```

No failure path converts to OFFLINE.

## 7. Contract tests

`tests/gate1/test_douyin_formal_adapter.py` adds twelve checks covering:

```text
formal LivePlatformAdapter structural compatibility
provider identity resolution without internal ids
profile identity consistency
status 2 -> LIVE
status 4 -> OFFLINE
unrecognized/missing status -> UNKNOWN
provider operation failure -> UNKNOWN
timeout/network failure -> UNKNOWN
live identity mismatch -> UNKNOWN
stable profile URL remains canonical over room metadata
wrong-platform account rejection
no legacy/state-engine/session/event/commit ownership
```

With the accepted 132-test Gate 1 baseline, the expected complete suite after
this slice is 144 tests.

## 8. Acceptance

Gate 1.3-3 is not PASS merely because the adapter file exists.

Current acceptance target:

```text
A. Gate 1.3-2 PASS / CLOSED                         PASS
B. formal Douyin adapter core landed                PASS / CODE
C. evidence-backed 2/4 mapping frozen               PASS / CODE
D. stable identity rules frozen                     PASS / CODE
E. failure -> UNKNOWN preserved                     PASS / CODE
F. no legacy runtime import                         PASS / CONTRACT
G. dedicated Douyin adapter contracts               PENDING / 12
H. complete Gate 1 suite                            PENDING / expected 144
I. provider-backed transport/probe evidence          NOT YET ACCEPTED
```

G-H validate the formal semantic migration. A later step in Gate 1.3-3 must wire
an evidence-backed provider gateway and exercise it without importing the legacy
adapter inward before Gate 1.3-3 can close PASS.

## 9. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy platform_adapters imported into stage_letter runtime
raw status other than accepted 2/4 guessed as decisive truth
request/parse/auth failure -> OFFLINE
room URL treated as canonical creator identity
stale title treated as live-state evidence
provider identity mismatch silently accepted
adapter opening/closing LiveSession or creating LiveEvent
fabricating the deferred Gate 0A lifecycle evidence
```
