# Gate 5.2 — Audited Platform Controls Acceptance

Date: 2026-08-20

Status: PASS / CLOSED

## Controlled browser-to-database journey

1. An authenticated operator used the Admin page to disable Bilibili.
2. Read-only PostgreSQL verification observed `HEALTHY → DISABLED` in
   `platform_health` and a matching append-only audit record with
   `DISABLE / HEALTHY / DISABLED`.
3. The operator then used the Admin page to restore Bilibili.
4. Read-only verification observed `DISABLED → DEGRADED`, never directly to
   `HEALTHY`, and a second matching audit record with
   `ENABLE / DISABLED / DEGRADED`.

The transition is platform-level operational control. It did not invoke a
provider, send a notification, consume a grant, or modify historical live
observations, sessions, events, or deliveries.

## Automated evidence

- Gate 5: `11 passed`;
- Gate 1–5 regression: `615 passed, 173 subtests passed`;
- migration head: `f52a9d1c4e81`.

## Boundaries

- Only the four supported platforms are manageable; synthetic acceptance
  platforms and arbitrary names are rejected.
- The audit record stores the authenticated actor, target platform, requested
  action, prior/resulting state, and timestamp. It stores no credential.
- This controlled operational action neither closes Gate 0A nor approves
  production or exactly-once behavior.
