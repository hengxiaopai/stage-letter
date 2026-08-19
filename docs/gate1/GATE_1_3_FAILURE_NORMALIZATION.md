# Gate 1.3-2 — Provider Error / Ambiguity Normalization

Status: **CURRENT / CODE + CONTRACTS LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.3-1 PASS / CLOSED.

## 1. Purpose

Gate 1.3-2 freezes how provider/transport failures and ambiguous responses are
represented before any concrete provider adapter is migrated into the formal
runtime.

The rule is intentionally conservative:

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

## 2. Diagnostic failure vocabulary

Formal infrastructure now defines `ProviderFailureKind`:

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

These values are diagnostic infrastructure vocabulary, not additions to formal
`LiveStatus`. Canonical live truth remains exactly:

```text
LIVE
OFFLINE
UNKNOWN
```

## 3. HTTP normalization

`classify_http_failure()` provides conservative transport classification:

```text
401      -> AUTH_REQUIRED
403      -> FORBIDDEN
404      -> NOT_FOUND
429      -> RATE_LIMITED
5xx      -> UPSTREAM_ERROR
other    -> UNKNOWN
```

None of those classifications implies OFFLINE.

## 4. Exception normalization

`classify_exception()` only infers categories that Python exception type makes
safe to infer:

```text
TimeoutError      -> TIMEOUT
ConnectionError   -> NETWORK
other exception   -> UNKNOWN
```

Parse/schema/captcha/ambiguity categories must be supplied explicitly by the
provider-specific implementation when evidence supports them. Generic exception
text is not parsed to invent a stronger classification.

## 5. Failure -> live snapshot

`unknown_snapshot_for_failure()` preserves the external account identity,
observation time, source, room id, and canonical URL while producing:

```text
status = UNKNOWN
source_started_at = None
title = None
```

The normalizer deliberately does not invent live metadata from a failed request.
Diagnostic details remain in `ProviderFailure`; they are not smuggled into
canonical live truth.

## 6. Explicit status mapping

`normalize_explicit_status()` is the only generic status helper introduced in
this slice.

Concrete adapters supply provider-specific sets of explicit LIVE and OFFLINE
values. Any unrecognized/missing value returns UNKNOWN. LIVE/OFFLINE value sets
must be disjoint.

Example shape:

```text
raw value in explicit live set     -> LIVE
raw value in explicit offline set  -> OFFLINE
anything else                      -> UNKNOWN
```

The actual Douyin/Bilibili/Huya/Douyu value mappings remain Gate 1.3-3/1.3-4
work and must be evidence-backed.

## 7. Operation errors outside live snapshot reads

`ProviderOperationError` carries a normalized `ProviderFailure` for operations
such as identity/profile resolution where returning a `LiveSnapshot` is not the
right contract.

It does not encode live truth and its existence must never be interpreted as
OFFLINE by callers.

## 8. Contract tests

Landed:

```text
tests/gate1/test_provider_failure_normalization.py
```

The eleven contracts verify:

```text
diagnostic failure vocabulary is separate from live truth
HTTP failure classification
safe exception classification
all failure kinds -> UNKNOWN live snapshot
identity/source provenance is preserved
failed reads do not invent source_started_at/title
explicit LIVE/OFFLINE values map only when recognized
unrecognized/missing status -> UNKNOWN
overlapping status sets rejected
ProviderOperationError carries diagnostic failure only
normalizer has no legacy imports or session/event ownership
```

## 9. Acceptance

Gate 1.3-2 PASS requires:

```text
A. Gate 1.3-1 PASS / CLOSED                          PASS
B. diagnostic failure vocabulary landed              PASS / CODE
C. HTTP/exception classification landed              PASS / CODE
D. every failure/ambiguity maps to UNKNOWN truth     CONTRACT LANDED
E. explicit provider status mapping is conservative  CONTRACT LANDED
F. no invented live metadata on failure              CONTRACT LANDED
G. no legacy runtime dependency                      CONTRACT LANDED
H. dedicated normalization contracts pass            PENDING / 11
I. complete Gate 1 suite remains green               PENDING / expected 132
```

Gate 1.3-2 remains **CURRENT** until H-I pass.

## 10. Stop rules

Stop with FAIL/BLOCKED if implementation pressure requires:

```text
403/404/429/timeout/parse/captcha/ambiguity -> OFFLINE
new provider-specific values added to formal LiveStatus
exception-message guessing promoted to canonical status
failure response inventing source_started_at/title
provider diagnostic details persisted as canonical state
legacy platform_adapters imported inward
state/session/event mutation inside failure normalization
```
