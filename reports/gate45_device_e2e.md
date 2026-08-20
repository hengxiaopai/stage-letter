# Gate 4.5 — Developer Tools / Device E2E Acceptance

Date: 2026-08-20

Status: PASS / CLOSED

## Evidence chain

1. WeChat Developer Tools recompiled the native Mini Program and rendered the
   home, subscriptions, profile, and add-subscription pages against the local
   API. Component-WXSS selector and `scroll-view` flex compatibility warnings
   found during this run were repaired and covered by Gate 4.5 regression tests.
2. A real user-driven `wx.requestSubscribeMessage` acceptance was recorded by
   the durable grant-intake endpoint. No grant was fabricated.
3. A disabled, isolated controlled account produced a canonical
   `LIVE_STARTED / TRANSITION` event after the follow timestamp. It was never
   enabled for platform monitoring, so this is not platform-lifecycle evidence.
4. The real WeChat provider accepted one controlled message (`errcode=0`); the
   durable delivery became `SENT`, one grant was consumed, and the same state
   survived a fresh runtime/database read.
5. The first device message exposed two acceptance-only configuration defects:
   the controlled sender omitted the canonical detail `page`, then used the
   unpublished `formal` Mini Program state. The sender now supplies
   `pages/detail/index?id=<positive creator id>` and targets the uploaded
   `developer` version for device acceptance.
6. After a user-driven re-authorization and developer-version upload, the phone
   received the corrected controlled message. The user tapped it and confirmed
   that the Mini Program opened the corresponding anchor-detail page.

## Automated evidence

- Gate 4: `47 passed`;
- Gate 1–4 regression: `603 passed, 173 subtests passed`;
- Alembic head: `e34d7a2c1b50`.

## Boundaries

- Provider acceptance, device receipt, and user click are separately observed
  here; no user-read mutation is inferred.
- No openid, template identifier, login code, AppSecret, access token, or
  database credential is recorded.
- Controlled accounts/events and accepted deliveries remain durable audit
  evidence; they are isolated from production monitoring.
- This does not close Gate 0A, claim exactly-once behavior, or approve a
  production release.
