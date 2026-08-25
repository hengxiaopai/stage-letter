# UI V2.2 D4 — Formal LiveSession Consumer Parity

## Outcome

Legacy and Formal producers now persist one consumer-compatible LiveSession
shape. The anchor detail API reads persisted facts instead of substituting
`正在直播` or `直播` for Formal rows.

## Frozen field contract

| Field | Availability | Source / rule | Null policy |
|---|---|---|---|
| `title` | NOW | normalized provider live snapshot | null means provider did not supply it; UI may use neutral fallback copy |
| `cover` | NOW | normalized provider live snapshot | null means no trustworthy cover |
| `viewer_count` | NOW | normalized non-negative integer | null means unavailable; never display as zero |
| `provider_room_id` | NOW | provider room identity, always stored as text | null is allowed; it does not imply offline |
| `metadata_source` | NOW | adapter/provider evidence source | null only for historical rows |
| `metadata_observed_at` | NOW | time the metadata snapshot was observed | null only for historical rows |
| `started_at` response | DERIVED | `source_started_at` when trustworthy, otherwise persisted session-open time | required |
| `started_at_source` | DERIVED | `platform` or `probe` | required for new Legacy/Formal rows |
| raw provider payload | FUTURE / excluded | not a consumer contract | never persisted as LiveSession metadata |

Provider IDs remain strings across domain and API boundaries. Provider
`owner.modify_time` is not accepted as a live start time.

## Session identity rule

`platform_account_id` identifies the creator account. A non-empty
`provider_room_id` identifies one provider room for an already-confirmed LIVE
session.

- Same account + same room: update non-null metadata on the current session.
- Same account + previously unknown room: enrich the current session.
- Same account + changed non-empty room: close the old session and create a new
  session in the same transaction boundary.
- Missing or changed room identity never decides LIVE/OFFLINE. The state machine
  must already have accepted decisive LIVE evidence.

The new session emits a live-start event so notification fan-out remains tied
to the new session identity.

## Persistence

Migration `a54e8b3c2d61` adds:

- `live_sessions.provider_room_id VARCHAR(128)`
- `live_sessions.metadata_source VARCHAR(64)`
- `live_sessions.metadata_observed_at TIMESTAMPTZ`
- composite lookup index on account, room, and start time

Existing `title`, `cover`, and `viewer_count` columns are now mapped by both ORM
models. Formal session creation also fills the compatibility `anchor_id`,
`platform`, `state`, and `started_at_source` columns so Legacy consumers see the
same row shape.

Formal observations store only normalized consumer-safe metadata in the
existing `provenance` JSONB envelope. Raw provider responses and raw errors are
not persisted there.

## Consumer contract

Anchor-detail current and recent sessions return persisted title, cover,
viewer count, timestamps, and timestamp source for both Legacy and Formal rows.
No producer-specific placeholder title is injected by the Formal fallback.

## Evidence

- Alembic: `f52a9d1c4e81 -> a54e8b3c2d61` PASS on local PostgreSQL 16.
- Gate 1 regression: `437 passed, 161 subtests passed`.
- Focused D4 contracts: `48 passed`.
- Anchor-detail/read-model regression: `10 passed`.
- Safe PostgreSQL probe: `tests/test_gate54_live_session_pg.py` PASS.
  The probe validates metadata refresh, room rollover, and Formal-to-Legacy row
  readability, then rolls back all probe data.

## Explicit non-goals

- No visual redesign or Mini Program layout change.
- No session calendar/statistics endpoints (D2).
- No user-authored streamer profile/community fields (D3).
- No claim that provider metadata is always present.
