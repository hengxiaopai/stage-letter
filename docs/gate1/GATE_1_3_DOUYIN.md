# Gate 1.3-3 — Douyin Formal Adapter Migration

Status: **CURRENT / FORMAL ADAPTER CORE PASS / STREAMGET GATEWAY LANDED / PROVIDER EVIDENCE PENDING**

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

## 2. Formal adapter core — accepted local evidence

Landed:

```text
stage_letter/infrastructure/platforms/douyin.py
tests/gate1/test_douyin_formal_adapter.py
```

User-local evidence:

```text
Dedicated Douyin formal-adapter contracts: 12 / 12 PASS
Complete Gate 1 suite:                    144 / 144 PASS
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

## 3. Formal StreamGet gateway — landed

New formal provider transport:

```text
stage_letter/infrastructure/platforms/douyin_streamget.py
tests/gate1/test_douyin_streamget_gateway.py
scripts/gate13_douyin_provider_probe.py
```

The runtime chain is now:

```text
StreamGetDouyinGateway
  -> DouyinProviderGateway
      -> DouyinFormalAdapter
          -> LiveSnapshot
```

`StreamGetDouyinGateway` uses only stable PROFILE/sec_uid reads through
StreamGet `fetch_app_stream_data()` and does not import the legacy
`platform_adapters/*` package or Gate 0 experiments.

StreamGet is imported lazily only when a real provider call occurs. Importing the
formal platform package therefore does not itself require the optional provider
library to be installed.

## 4. Provider transport rules

Stable identity input accepted by the gateway:

```text
raw sec_uid
https://www.douyin.com/user/<sec_uid>
```

Historical live-room URLs are deliberately rejected as identity inputs.
The gateway canonicalizes monitoring identity to:

```text
https://www.douyin.com/user/<sec_uid>
```

The provider gateway returns raw records only. Canonical status normalization
remains owned by `DouyinFormalAdapter`:

```text
raw integer 2 -> LIVE
raw integer 4 -> OFFLINE
all other values -> UNKNOWN
```

String lookalikes such as `"2"` / `"4"` remain UNKNOWN until separately proven.

## 5. Failure and identity safety

Gateway transport exceptions are normalized to `ProviderOperationError` with the
Gate 1.3-2 diagnostic vocabulary. The formal adapter then maps live-read failures
to UNKNOWN, never OFFLINE.

```text
TimeoutError          -> TIMEOUT diagnostic -> UNKNOWN
ConnectionError       -> NETWORK diagnostic -> UNKNOWN
generic wrapper error -> UNKNOWN diagnostic -> UNKNOWN
non-dict payload      -> SCHEMA_DRIFT diagnostic -> UNKNOWN
explicit sec_uid mismatch -> AMBIGUOUS diagnostic -> UNKNOWN
```

If StreamGet returns an explicit sec_uid-like field, a mismatch is rejected. If
it does not expose such a field, the request remains bound to the stable profile
URL constructed from the requested sec_uid; no alternative room URL is promoted
into canonical identity.

## 6. Metadata rules

The gateway may pass through provider metadata when explicitly present:

```text
anchor_name -> display_name
id / room_id -> room metadata
title -> title metadata
start_time positive unix seconds -> candidate source_started_at
```

No avatar/bio is invented when the StreamGet room record does not establish those
facts.

`DouyinFormalAdapter` still enforces:

```text
source_started_at accepted only for explicit LIVE
OFFLINE / UNKNOWN -> source_started_at = None
stale title never overrides explicit state
canonical_url comes from stable profile identity
```

## 7. Provider-backed probe

Run the formal chain directly:

```text
python scripts/gate13_douyin_provider_probe.py <sec_uid-or-profile-url> --expect LIVE
python scripts/gate13_douyin_provider_probe.py <sec_uid-or-profile-url> --expect OFFLINE
```

The probe exercises only:

```text
StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot
```

It does not import legacy adapters or Gate 0 experiments. Optional
`DOUYIN_COOKIE` is read from the environment but only the boolean
`cookie_configured` is emitted; the cookie value is never printed.

Probe output deliberately preserves:

```text
gate0a_status = DEGRADED
production_approved = false
```

A provider-backed run is technical evidence only, not production authorization.

### First provider-run harness finding

The first LIVE and OFFLINE operator attempts both returned UNKNOWN before a real
provider call because the shell argument had been copied as a Markdown-rendered
link instead of a raw URL:

```text
[https://www.douyin.com/user/<sec_uid>](https://www.douyin.com/user/<sec_uid>)
```

That wrapper is not a canonical gateway identity, so the strict gateway rejected
it as an input failure. This is not accepted as LIVE/OFFLINE provider evidence.

The probe CLI has now been hardened without weakening the gateway contract:

```text
raw URL / sec_uid                       -> unchanged
Markdown link with identical label/url -> safely unwrap to raw URL
Markdown link with different target    -> reject
```

Failure output now also preserves the requested expectation, whether CLI input
normalization occurred, and the normalized failure detail. No cookie value or raw
provider payload is printed.

`tests/gate1/test_douyin_provider_probe_cli.py` adds three deterministic CLI
normalization checks.

## 8. Gateway and probe contracts

`tests/gate1/test_douyin_streamget_gateway.py` adds ten checks covering:

```text
raw sec_uid -> stable profile URL
profile URL -> same sec_uid
historical live URL rejection
profile mapping without invented avatar/bio
raw status and metadata pass-through
explicit positive start_time parsing only
timeout/network normalization
generic runtime failure -> UNKNOWN diagnostic
explicit response identity mismatch -> AMBIGUOUS
lazy StreamGet loading + no legacy/runtime/state ownership
```

`tests/gate1/test_douyin_provider_probe_cli.py` adds three checks covering raw
identity preservation, safe equal-target Markdown unwrapping, and rejection of a
mismatched Markdown target.

Starting from the accepted 144-test baseline, the expected complete Gate 1 suite
is now 157 tests.

## 9. Acceptance

Current Gate 1.3-3 acceptance state:

```text
A. Gate 1.3-2 PASS / CLOSED                         PASS
B. formal Douyin adapter core landed                PASS
C. dedicated formal adapter contracts               PASS / 12
D. complete pre-gateway Gate 1 suite                 PASS / 144
E. evidence-backed 2/4 mapping frozen               PASS
F. stable identity rules frozen                     PASS
G. failure -> UNKNOWN preserved                     PASS
H. no legacy runtime import                         PASS / CONTRACT
I. formal StreamGet gateway landed                  PASS / CODE
J. gateway contract tests                           PENDING / 10
K. provider-probe CLI normalization contracts       PENDING / 3
L. complete Gate 1 suite after gateway/probe CLI    PENDING / expected 157
M. provider-backed decisive LIVE probe              PENDING
N. provider-backed decisive OFFLINE probe           PENDING
```

Gate 1.3-3 remains **CURRENT** until J-N pass.

Provider-backed acceptance should use creators whose LIVE/OFFLINE state is
independently checked at probe time. The provider probe must agree with that
current ground truth. This does not close the separate Gate 0A lifecycle gap.

## 10. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy platform_adapters imported into stage_letter runtime
experiments imported into formal runtime
raw status other than accepted integer 2/4 guessed as decisive truth
request/parse/auth failure -> OFFLINE
room URL treated as canonical creator identity
stale title treated as live-state evidence
provider identity mismatch silently accepted
adapter/gateway opening or closing LiveSession or creating LiveEvent
printing provider cookies/secrets in probe output
fabricating the deferred Gate 0A lifecycle evidence
```
