# Gate 4.4 — Notification Tap + Anchor Detail Acceptance

Date: 2026-08-20

Status: PASS

## Scope

- WeChat Developer Tools Stable `1.06.2504010`
- existing PostgreSQL notification history only
- canonical notification target validation
- user-driven history-row navigation to the formal Creator detail route
- detail identity validation before API read

## Observed journey

1. The Mini Program logged in and loaded the current subscribed-creator home state.
2. The first profile read exposed a real client/API mismatch: the client sent
   `cursor=0`, while Gate 3 defines an optional opaque keyset cursor. The API
   correctly returned HTTP `422`.
3. The initial request was repaired to omit the cursor. A dedicated regression
   test freezes that boundary.
4. The Developer Tools retry loaded one existing notification-history row.
5. Clicking that existing row navigated to `pages/detail/index` through the
   server-supplied canonical formal Creator identity.
6. The anchor-detail API returned HTTP `200`, and the Mini Program rendered the
   corresponding creator and live-session state.

## Automated evidence

- Gate 4.4 precise tests: `11 passed`
- Gate 4 tests: `42 passed`
- Gate 1–4 cumulative regression: `598 passed, 173 subtests passed`
- Alembic head unchanged: `e34d7a2c1b50`
- JavaScript syntax checks passed for profile, detail, and notification service

## Boundaries

- No notification fixture or acceptance row was inserted for this journey.
- No provider message was sent, no grant was consumed, and no read marker was
  written.
- This proves Developer Tools history loading, canonical navigation, and detail
  rendering. It does not prove device receipt, a real WeChat notification tap,
  exactly-once behavior, production readiness, or Gate 0A closure.
- No openid, login code, template identifier, AppSecret, access token, session
  key, database credential, or local network address is recorded here.
