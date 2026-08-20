# Gate 4.3 — Paste-Link Subscription + Permission Acceptance

Date: 2026-08-20

Status: PASS

## Scope

- WeChat Developer Tools Stable `1.06.2504010`
- Bilibili creator URL: `https://space.bilibili.com/299312132`
- real Mini Program login already accepted under Gate 4.1
- real paste-link parse and user-driven subscribe action
- PostgreSQL persistence verification without printing user or WeChat identifiers

## Observed journey

1. Paste-link parsing returned a confirmed Bilibili creator card.
2. The first authorized subscribe attempt returned HTTP `500`.
3. Isolated reproduction showed PostgreSQL rejecting a null Gate 1
   `platform_accounts.creator_id`; the failed request rolled back completely.
4. The compatibility write was repaired to persist both the formal Gate 1
   creator/follow truth and the temporary legacy page bridge in one transaction.
5. A dedicated diagnostic request returned HTTP `200`; all eight diagnostic rows
   were then removed by exact diagnostic identity before the real retry.
6. The authorized Developer Tools retry returned HTTP `200` and a valid
   subscription response.
7. Read-only verification confirmed Creator, CreatorProfile, PlatformAccount,
   Follow, enabled NotificationPreference, Anchor, and UserSubscription agree on
   the accepted identity bridge.
8. No grant intake or accepted grant was produced by Developer Tools in this
   run. The subscription therefore uses the accepted durable `IN_APP` fallback;
   no grant balance was invented.

## Automated evidence

- Gate 4.3 precise tests: `8 passed`
- Gate 1–4 cumulative regression: `587 passed, 173 subtests passed`
- Alembic head unchanged: `e34d7a2c1b50`

## Boundaries

- This proves paste-link parsing, a real user-driven subscribe action,
  PostgreSQL persistence, and fallback selection.
- It does not prove WeChat provider delivery, device receipt, notification tap,
  user read, exactly-once behavior, production readiness, or Gate 0A closure.
- No openid, login code, template identifier, AppSecret, access token, session
  key, or database credential is recorded here.
