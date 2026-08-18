# Gate 0C-4 — Source Composition Contract

Status: **IMPLEMENTED / PENDING ACCEPTANCE RUN**

## Purpose

Gate 0C-4 freezes how multiple monitoring sources contribute creator truth and metadata without allowing source failures, null fields or disagreement to manufacture a false LIVE/OFFLINE transition.

Canonical implementation:

```text
experiments/gate0c/source_composition.py
experiments/gate0c/test_source_composition.py
```

## Current Stage Letter source roles

The generic policy supports four roles:

```text
PRIMARY_STATUS
    authoritative for decisive LIVE and OFFLINE

POSITIVE_STATUS
    may contribute/fallback LIVE
    can never create OFFLINE

FULL_STATUS
    optional future fallback capable of LIVE and OFFLINE
    not assigned to current TikHub/F2 paths

METADATA_ONLY
    cannot contribute creator status
```

Current candidate deployment mapping from Gate 0A evidence:

```text
StreamGet PROFILE -> PRIMARY_STATUS
TikHub            -> POSITIVE_STATUS + metadata enrichment
F2                -> POSITIVE_STATUS + metadata enrichment
```

`FULL_STATUS` exists only as a provider-agnostic policy capability. It is not evidence that TikHub/F2 have reliable OFFLINE authority.

## Frozen safety rules

```text
status authority != metadata authority

provider health != creator live state

null room_id/title/live_url/source_started_at != OFFLINE

POSITIVE_STATUS OFFLINE claim -> ignored for canonical status

primary UNKNOWN + recent positive LIVE -> LIVE fallback candidate
    Gate 0B confirmation hysteresis still applies downstream

primary OFFLINE + recent authorized positive LIVE -> CONFLICT -> UNKNOWN

primary LIVE + POSITIVE_STATUS OFFLINE -> primary LIVE remains decisive

recent opposing FULL_STATUS claims -> CONFLICT -> UNKNOWN

CONFLICT never silently chooses one source

UNKNOWN / CONFLICT cannot close a Gate 0B LiveSession
```

## Freshness, ordering and idempotency

Each source stores only its latest accepted observation.

```text
duplicate observation_id
    -> DUPLICATE
    -> no mutation

older observation from same source
    -> STALE
    -> no mutation

same timestamp with different IDs
    -> accepted; deterministic observation-id tie break
```

Status fallback/conflict arbitration is bounded by configurable freshness windows. Old auxiliary LIVE facts eventually age out and cannot indefinitely block a newer primary OFFLINE fact.

`ComposerSnapshot` / `SourceComposer.from_snapshot()` preserve the latest per-source facts and seen observation IDs across a persistence boundary.

## Metadata composition

Metadata is composed independently from status. Fields currently covered:

```text
room_id
title
live_url
source_started_at
```

Each selected field carries provenance:

```text
source_id
observation_id
observed_at
```

A metadata source may fail or return null while a decisive canonical status remains valid. Missing metadata is never interpreted as an OFFLINE fact.

`source_started_at` is only populated when a source explicitly supplies it. No timestamp is invented from local detection time.

## Acceptance matrix

```text
01 primary LIVE is canonical                                      PENDING CI
02 primary OFFLINE is canonical                                   PENDING CI
03 primary UNKNOWN + positive LIVE -> LIVE fallback               PENDING CI
04 POSITIVE_STATUS OFFLINE cannot create OFFLINE                  PENDING CI
05 primary OFFLINE + recent positive LIVE -> CONFLICT/UNKNOWN     PENDING CI
06 primary LIVE ignores positive-only OFFLINE claim               PENDING CI
07 opposing FULL_STATUS can create explicit conflict              PENDING CI
08 old fallback outside freshness window cannot override primary  PENDING CI
09 missing metadata never changes primary status                  PENDING CI
10 auxiliary room_id enriches primary LIVE                        PENDING CI
11 METADATA_ONLY source cannot create LIVE/OFFLINE                PENDING CI
12 degraded health does not rewrite decisive status               PENDING CI
13 unavailable + UNKNOWN never becomes OFFLINE                    PENDING CI
14 duplicate observation ID is idempotent                         PENDING CI
15 older same-source result is stale                              PENDING CI
16 snapshot restore preserves facts/idempotency                   PENDING CI
17 source_started_at remains explicit + provenance-bearing        PENDING CI
18 conflict UNKNOWN cannot close Gate 0B open LiveSession         PENDING CI
19 account identity mismatch rejected                             PENDING CI
20 invalid policy rejected                                        PENDING CI
```

## Gate close condition

Gate 0C-4 may be marked PASS only after the deterministic acceptance suite is green in CI (or an equivalent clean local acceptance run is captured), with the source-composition syntax check included in `Gate 0C Health Smoke`.

After 0C-4 PASS, Gate 0C overall may close and Gate 0D — WeChat Notification Truth may begin. Production authorization/compliance remains a separate unresolved constraint and is not silently waived by this semantic Gate.
