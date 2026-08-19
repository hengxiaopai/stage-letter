# Gate 1.3-3 — Douyin Formal Adapter Migration

Status: **CURRENT / FORMAL ADAPTER CORE PASS / STREAMGET GATEWAY LANDED / PROVIDER LIVE+OFFLINE EVIDENCE PASS / FINAL LOCAL SUITE PENDING**

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
must not reinterpret this migration as proof of a real same-creator
OFFLINE -> LIVE -> OFFLINE lifecycle.

## 2. Formal adapter core — accepted local evidence

Landed:

```text
stage_letter/infrastructure/platforms/douyin.py
tests/gate1/test_douyin_formal_adapter.py
```

Accepted user-local evidence:

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

Formal provider transport:

```text
stage_letter/infrastructure/platforms/douyin_streamget.py
tests/gate1/test_douyin_streamget_gateway.py
scripts/gate13_douyin_provider_probe.py
requirements-provider-douyin.txt
```

The runtime chain is:

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

The optional provider runtime is pinned to the accepted Gate 0A baseline and
includes SOCKS transport support needed by proxied development environments:

```text
streamget==4.0.10
httpx[socks]>=0.27
```

## 4. Provider transport rules

Stable identity input accepted by the gateway:

```text
raw sec_uid
https://www.douyin.com/user/<sec_uid>
```

Historical live-room URLs are deliberately rejected as identity inputs. The
gateway canonicalizes monitoring identity to the stable profile/sec_uid path.

Canonical status normalization remains owned by `DouyinFormalAdapter`:

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
TimeoutError              -> TIMEOUT diagnostic -> UNKNOWN
ConnectionError           -> NETWORK diagnostic -> UNKNOWN
generic wrapper error     -> UNKNOWN diagnostic -> UNKNOWN
non-dict payload          -> SCHEMA_DRIFT diagnostic -> UNKNOWN
explicit sec_uid mismatch -> AMBIGUOUS diagnostic -> UNKNOWN
missing provider runtime  -> UNKNOWN diagnostic -> UNKNOWN
```

Earlier operator runs correctly surfaced two harness/runtime defects without
inventing live truth:

```text
Markdown-rendered copied URL -> strict input rejection / UNKNOWN
missing StreamGet runtime    -> ModuleNotFoundError diagnostic / UNKNOWN
missing SOCKS support        -> Node runtime install failure
```

Those were repaired without weakening the formal gateway contract.

## 6. Decisive provider-backed evidence — PASS

After the provider runtime was installed successfully, the operator executed the
formal provider chain against two creators whose current state had been
independently checked at probe time.

### LIVE control

```text
creator             大坤坤
expected            LIVE
observed             LIVE
expectation_match    true
source               streamget.profile
cookie_configured    false
production_approved  false
observed_at UTC      2026-08-19T05:35:44.743960+00:00
```

Result: **PASS / decisive LIVE provider evidence**.

### OFFLINE control

```text
creator             陈泽-
expected            OFFLINE
observed             OFFLINE
expectation_match    true
source               streamget.profile
cookie_configured    false
production_approved  false
observed_at UTC      2026-08-19T05:35:59.172957+00:00
```

Result: **PASS / decisive OFFLINE provider evidence**.

Both runs exercised the formal chain:

```text
StreamGetDouyinGateway -> DouyinFormalAdapter -> LiveSnapshot
```

No legacy adapter or Gate 0 experiment was imported inward. The runs required no
Douyin cookie and retained `gate0a_status = DEGRADED` and
`production_approved = false`.

These two probes close the Gate 1.3-3 provider transport evidence requirement.
They do **not** close the separate Gate 0A same-creator lifecycle gap.

## 7. Metadata observations from accepted probes

Both decisive probes returned `room_id = null` and `source_started_at = null`.
Those fields therefore remain optional provider metadata; their absence does not
invalidate the decisive explicit state result and must not be fabricated.

The OFFLINE probe also returned title metadata while status was OFFLINE, further
preserving the Gate 0A rule that title presence is not canonical live-state
truth.

## 8. Gateway and probe contracts

`tests/gate1/test_douyin_streamget_gateway.py` adds ten gateway contracts and
`tests/gate1/test_douyin_provider_probe_cli.py` adds three CLI-input contracts.

Starting from the accepted 144-test baseline, the expected complete Gate 1 suite
is 157 tests.

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
J. optional provider runtime dependency             PASS / INSTALLED
K. provider-backed decisive LIVE probe              PASS
L. provider-backed decisive OFFLINE probe           PASS
M. gateway contract tests                           PENDING / 10
N. provider-probe CLI normalization contracts       PENDING / 3
O. complete Gate 1 suite after gateway/probe CLI    PENDING / expected 157
```

Gate 1.3-3 remains **CURRENT** until M-O pass.

If M-O pass, Gate 1.3-3 may close **PASS / CLOSED** without adding another real
provider requirement. Gate 0A remains DEGRADED independently.

## 10. Stop rules

Stop with FAIL/BLOCKED if progress requires:

```text
legacy platform_adapters imported into stage_letter runtime
experiments imported into formal runtime
raw status other than accepted integer 2/4 guessed as decisive truth
request/parse/auth/dependency failure -> OFFLINE
room URL treated as canonical creator identity
stale title treated as live-state evidence
provider identity mismatch silently accepted
adapter/gateway opening or closing LiveSession or creating LiveEvent
printing provider cookies/secrets in probe output
fabricating the deferred Gate 0A lifecycle evidence
```
