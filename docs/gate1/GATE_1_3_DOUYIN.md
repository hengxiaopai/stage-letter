# Gate 1.3-3 — Douyin Formal Adapter Migration

Status: **PASS / CLOSED**

Entry authority: Gate 1.3-2 PASS / CLOSED.

## 1. Accepted evidence authority

Gate 1.3-3 migrated only Douyin semantics already established by Gate 0A evidence:

```text
raw_room_status = 2 -> LIVE
raw_room_status = 4 -> OFFLINE
anything else / request failure / parse failure -> UNKNOWN
PROFILE/sec_uid repeated LIVE stability    PASS 3/3
PROFILE/sec_uid repeated OFFLINE stability PASS 3/3
initial multi-creator validation           PASS 6/6
failure safety                             PASS
```

Stable profile/sec_uid identity remains the monitoring key. Historical room URLs,
stale titles, missing metadata, and provider failures are not canonical state
truth.

Gate 0A remains **DEGRADED / DEFERRED** for the separate same-creator
`OFFLINE -> LIVE -> OFFLINE` lifecycle gap.

## 2. Formal runtime accepted

```text
stage_letter/infrastructure/platforms/douyin.py
stage_letter/infrastructure/platforms/douyin_streamget.py
scripts/gate13_douyin_provider_probe.py
requirements-provider-douyin.txt
```

Runtime chain:

```text
StreamGetDouyinGateway
  -> DouyinProviderGateway
      -> DouyinFormalAdapter
          -> LiveSnapshot
```

The formal runtime does not import legacy `platform_adapters/*`, Gate 0
`experiments/*`, `core/*`, `api/*`, or `workers/*` inward.

The provider runtime baseline is:

```text
streamget==4.0.10
httpx[socks]>=0.27
```

## 3. Accepted provider-backed evidence

LIVE control:

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

OFFLINE control:

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

Both are decisive technical transport evidence through the formal chain. Neither
upgrades production authorization or the separate Gate 0A lifecycle status.

## 4. Accepted local regression

Final user-local evidence:

```text
Douyin formal-adapter contracts:          12 / 12 PASS
StreamGet gateway contracts:              10 / 10 PASS
Provider-probe CLI normalization:          3 / 3 PASS
Complete Gate 1 suite after provider work: 157 / 157 PASS
```

Earlier harness/runtime failures were also verified to fail conservatively:

```text
Markdown-rendered copied URL -> UNKNOWN/input rejection
missing StreamGet runtime    -> UNKNOWN/ModuleNotFoundError diagnostic
missing SOCKS support        -> provider runtime install failure
```

None produced false OFFLINE truth.

## 5. Acceptance result

```text
A. Gate 1.3-2 PASS / CLOSED                         PASS
B. formal Douyin adapter core                       PASS
C. evidence-backed integer 2/4 mapping              PASS
D. stable profile/sec_uid identity rules            PASS
E. failure -> UNKNOWN                               PASS
F. no legacy runtime import                         PASS
G. StreamGet formal gateway                         PASS
H. decisive LIVE provider probe                     PASS
I. decisive OFFLINE provider probe                  PASS
J. adapter contracts                                PASS / 12
K. gateway contracts                                PASS / 10
L. provider-probe CLI contracts                     PASS / 3
M. complete Gate 1 suite                            PASS / 157
```

Gate 1.3-3: **PASS / CLOSED**.

Next: Gate 1.3-4 — Bilibili / Huya / Douyu Formal Adapter Migration.

## 6. Preserved stop rules

The accepted Douyin behavior must not later be weakened by:

```text
legacy platform_adapters imported into stage_letter runtime
experiments imported into formal runtime
raw status other than accepted integer 2/4 guessed as decisive truth
request/parse/auth/dependency failure -> OFFLINE
historical room URL replacing stable creator identity
stale metadata overriding explicit provider status
provider identity mismatch silently accepted
adapter/gateway opening or closing LiveSession or creating LiveEvent
printing provider cookies/secrets in probe output
fabricating the deferred Gate 0A lifecycle evidence
```
