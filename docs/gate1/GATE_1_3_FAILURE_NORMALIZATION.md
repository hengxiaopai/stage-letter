# Gate 1.3-2 — Provider Error / Ambiguity Normalization

Status: **PASS / CLOSED**

Entry authority: Gate 1.3-1 PASS / CLOSED.

## 1. Purpose

Gate 1.3-2 freezes how provider/transport failures and ambiguous responses are
represented before concrete provider adapters enter the formal runtime.

The accepted conservative rule is:

```text
provider failure / ambiguity
  -> diagnostic ProviderFailure
  -> LiveSnapshot.status = UNKNOWN

never:
provider failure / ambiguity
  -> OFFLINE
```

Only explicit provider evidence mapped by a concrete adapter may produce LIVE or
OFFLINE.

## 2. Accepted diagnostic vocabulary

Infrastructure-only `ProviderFailureKind` remains:

```text
TIMEOUT
NETWORK
FORBIDDEN
RATE_LIMITED
AUTH_REQUIRED
CAPTCHA_REQUIRED
PARSE_ERROR
SCHEMA_DRIFT
AMBIGUOUS
NOT_FOUND
UPSTREAM_ERROR
UNKNOWN
```

These diagnostics are not additions to formal `LiveStatus`, which remains exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

## 3. Accepted normalization behavior

```text
401      -> AUTH_REQUIRED
403      -> FORBIDDEN
404      -> NOT_FOUND
429      -> RATE_LIMITED
5xx      -> UPSTREAM_ERROR
other    -> UNKNOWN diagnostic

TimeoutError     -> TIMEOUT
ConnectionError  -> NETWORK
other exception  -> UNKNOWN diagnostic
```

Every failure kind converts to an UNKNOWN live snapshot through
`unknown_snapshot_for_failure()` and does not invent `source_started_at` or
`title`.

`normalize_explicit_status()` maps only provider values explicitly supplied by a
concrete adapter:

```text
explicit live value     -> LIVE
explicit offline value  -> OFFLINE
anything else           -> UNKNOWN
```

LIVE and OFFLINE value sets must be disjoint.

## 4. Accepted local evidence

User-local acceptance:

```text
Dedicated provider-failure normalization contracts: 11 / 11 PASS
Complete Gate 1 suite:                         132 / 132 PASS
```

The dedicated contracts cover diagnostic/live-truth separation, HTTP and
exception classification, all-failure-to-UNKNOWN behavior, provenance
preservation, no invented live metadata, conservative explicit status mapping,
operation errors, and absence of legacy/session/event ownership.

## 5. Acceptance result

```text
A. Gate 1.3-1 PASS / CLOSED                          PASS
B. diagnostic failure vocabulary landed              PASS
C. HTTP/exception classification landed              PASS
D. every failure/ambiguity maps to UNKNOWN truth     PASS
E. explicit provider status mapping is conservative  PASS
F. no invented live metadata on failure              PASS
G. no legacy runtime dependency                      PASS
H. dedicated normalization contracts                 PASS / 11
I. complete Gate 1 suite                             PASS / 132
```

Gate 1.3-2: **PASS / CLOSED**.

Next: Gate 1.3-3 — Douyin Formal Adapter Migration.

## 6. Preserved stop rules

The accepted behavior must not later be weakened by:

```text
403/404/429/timeout/parse/captcha/ambiguity -> OFFLINE
provider-specific states added to formal LiveStatus
exception-message guessing promoted to canonical status
failure responses inventing source_started_at/title
legacy platform_adapters imported inward
state/session/event mutation inside provider normalization
```
