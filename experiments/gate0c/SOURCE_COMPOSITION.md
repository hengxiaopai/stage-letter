# Gate 0C-4 — Source Composition Contract

Status: **PASS**

## Purpose

Gate 0C-4 freezes how multiple monitoring sources contribute creator truth and metadata without allowing source failures, null fields or disagreement to manufacture a false LIVE/OFFLINE transition.

Canonical implementation:

```text
experiments/gate0c/source_composition.py
experiments/gate0c/test_source_composition.py
```

## Current source roles

```text
StreamGet PROFILE -> PRIMARY_STATUS
TikHub            -> POSITIVE_STATUS + metadata enrichment
F2                -> POSITIVE_STATUS + metadata enrichment
```

Generic policy roles:

```text
PRIMARY_STATUS
    decisive LIVE and OFFLINE authority

POSITIVE_STATUS
    may contribute/fallback LIVE
    can never create OFFLINE

FULL_STATUS
    optional future full fallback
    not assigned to current TikHub/F2 paths

METADATA_ONLY
    cannot contribute creator status
```

## Frozen safety rules

```text
status authority != metadata authority
provider health != creator live state
null metadata != OFFLINE
POSITIVE_STATUS OFFLINE -> ignored for canonical status
primary UNKNOWN + recent positive LIVE -> LIVE fallback candidate
primary OFFLINE + recent positive LIVE -> CONFLICT -> UNKNOWN
primary LIVE + POSITIVE_STATUS OFFLINE -> primary LIVE remains decisive
recent opposing FULL_STATUS claims -> CONFLICT -> UNKNOWN
UNKNOWN / CONFLICT cannot close a Gate 0B LiveSession
```

Freshness, ordering and idempotency are per source. Duplicate observation IDs are idempotent; older same-source observations are stale; snapshot restore preserves accepted facts and seen IDs.

Metadata is composed independently for `room_id`, `title`, `live_url`, and `source_started_at`, with field-level provenance (`source_id`, `observation_id`, `observed_at`). Missing metadata never changes canonical status, and `source_started_at` is never invented from local detection time.

## Acceptance — PASS 20/20

A clean local acceptance run on 2026-08-18 executed the complete Gate 0C suite:

```text
Gate 0C-1 Health                 19 PASS
Gate 0C-2 Poll Policy            16 PASS
Gate 0C-3 Fault Recovery         10 PASS
Gate 0C-4 Source Composition     20 PASS
----------------------------------------
Total                            65 PASS

Ran 65 tests in 0.022s
OK
```

The 0C-4 matrix specifically proved primary LIVE/OFFLINE authority, positive-only LIVE fallback, positive-source OFFLINE rejection, explicit conflict -> UNKNOWN, metadata provenance, duplicate/stale handling, snapshot restore, identity mismatch rejection, and that a composition conflict cannot close an already-open Gate 0B LiveSession.

## Gate result

```text
Gate 0C-4  PASS
Gate 0C    eligible to close
```

Production authorization/compliance remains a separate unresolved constraint and is not waived by this semantic Gate.
