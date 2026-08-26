# UI V2 D3 — Personal Streamer Profile Contract

## Scope and identity

D3 introduces a private streamer profile for the current user only. Its durable
identity is **`(user_id, creator_id)`** in `user_creator_profiles`; it does not
use `room_id` and does not default to `platform_account_id`. Existing Follow and
D1 NotificationPreference remain account-level facts and are not rewritten.

## Field truth classes

| Response layer / field | Class | Rule |
|---|---|---|
| `platform_facts.creator_id`, profile name/avatar/bio, platform accounts | NOW | existing Creator and platform-account facts; never overwritten by D3 PATCH |
| `user_alias`, `note`, `group`, `user_tags` | OPTIONAL | private user-authored data, keyed by user + Creator |
| `reference_schedule` | OPTIONAL | private reference plan in `Asia/Shanghai`; not platform schedule evidence |
| user-facing display combining the two layers | DERIVED | UI may prefer alias but must retain source layering |
| early/late, adherence, schedule prediction, community semantics | FUTURE | excluded from D3 and require a separately frozen Analysis Contract |

`reference_schedule.days_of_week` uses ISO-8601 weekday numbers in
`Asia/Shanghai`: `1=Monday` through `7=Sunday`. It cannot mutate LIVE/OFFLINE,
cannot generate a delivery, and cannot create an “early” or “late” platform
fact. D3 has no UI mock data.

## Ownership and lifecycle

GET/PATCH requires a current Formal Follow for the requested `(user_id, creator_id)`.
Two users can read the same platform Creator facts, but each can only receive and
modify their own `user_owned_profile`; no cross-user fallback or merge exists.

Unfollowing removes account-level Follow and D1 preference according to their
existing policy. D3 deliberately **retains** the private profile row. It becomes
unavailable while the user has no current Creator follow and becomes available
again after re-following the same Creator. This preserves a user's private note
without falsely treating a historic profile as an active subscription.

## API Contract

- `GET /api/v1/creators/{creator_id}/personal-profile?openid=`
- `PATCH /api/v1/creators/{creator_id}/personal-profile`

PATCH is field-level: omitted values are unchanged, `null` clears an OPTIONAL
field, and identical repeated PATCH requests have the same persisted state.
Responses use `platform_facts` and `user_owned_profile` as distinct objects.

## Database and acceptance

- Migration: `d31a7f4c9e20` (creates `user_creator_profiles`).
- D3.1 PostgreSQL concurrent acceptance uses independent transactions and explicit
  cleanup: two simultaneous first identical PATCH requests both succeed and leave
  one `(user_id, creator_id)` row; simultaneous alias-only and note-only PATCHes
  preserve both values. The lifecycle probe removes the last Follow, confirms
  GET/PATCH are unavailable while the profile row remains, then re-follows and
  verifies the original private profile is restored.
- Local Docker PostgreSQL clean upgrade: `c82e7a4d1f30 -> d31a7f4c9e20` PASS.
- Focused D3/D2/D1-adjacent Contract regression: `34 passed`; API import: PASS.

## Explicit non-goals

- no Mini Program or Figma changes;
- no migration of D1 notification preference;
- no platform live-state mutation, forecast, early/late analysis, or community feature.
