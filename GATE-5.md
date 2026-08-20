# Gate 5 — Admin / Observability

## Gate 5.0 — Baseline / Administrative Boundary Freeze

Status: IN PROGRESS

Gate 4 closed with `603 passed, 173 subtests passed`, migration head
`e34d7a2c1b50`, Developer Tools page acceptance, and a controlled WeChat
provider-to-device-to-detail journey. Gate 5 makes operational state visible and
intervenable without exposing customer data or weakening the accepted runtime
boundaries.

### Existing foundation

1. `GET /api/v1/system/health` already exposes API/worker heartbeat, persisted
   platform-health snapshots, and the operational Douyin login status.
2. Gate 2 persists probe telemetry and `platform_health`; its circuit-breaker
   administration service already owns explicit platform disable/enable actions.
3. Durable subscriptions, grant ledgers, notification deliveries, and history
   read models already exist. Gate 5 must query these existing records rather
   than create competing operational truth.
4. There is no Admin router, operator authentication/authorization boundary,
   audit trail, error aggregation read model, Prometheus exporter, or Admin Web
   surface in the accepted baseline.

### Gate 5 delivery slices

- **5.0** Baseline / Administrative Boundary Freeze. **PASS / CLOSED**
- **5.1** Protected Admin shell + read-only system/platform health. **PASS / CLOSED**
- **5.2** Audited platform enable/disable controls. **PASS / CLOSED**
- **5.3** Protected user, subscription, and notification-delivery inquiry. **PASS / CLOSED**
- **5.4** Metrics and bounded error aggregation. **PASS / CLOSED**
- **5.5** Restart-safe administrative end-to-end acceptance. **PASS / CLOSED**

### Frozen boundaries

1. **No public admin data.** Admin pages and APIs must require a server-side
   operator authorization boundary before they expose user, subscription,
   delivery, or health details.
2. **No secret in frontend or repository.** Operator credentials, AppSecret,
   database URLs, access tokens, and provider sessions stay in local/deployed
   secret configuration; neither Mini Program nor a committed browser bundle
   receives them.
3. **Operational controls are auditable.** A platform enable/disable action must
   identify the actor, target, requested state, result, and timestamp. It cannot
   rewrite historical observations, sessions, events, or notification outcomes.
4. **Health is operational evidence, not live truth.** Telemetry/heartbeat
   failures never mutate `LIVE / OFFLINE / UNKNOWN` into a fabricated value.
5. **Metrics are bounded.** No metric label may contain openid, creator name,
   canonical URL, delivery id, or unbounded provider response text.
6. **Existing notification semantics remain frozen.** Admin inquiry does not
   resend a delivery, manufacture a grant, mark a user read, or claim
   exactly-once behavior.
7. **Gate 0A remains DEGRADED and production remains unapproved.** Admin
   visibility and manual control do not close platform-lifecycle evidence gaps.

### Gate 5.0 acceptance

- the Roadmap places Gate 5 after the closed Mini Program gate;
- existing health/telemetry/control seams and missing admin safeguards are
  documented before implementing a management surface;
- Gate 5 makes no provider call, notification send, live-truth mutation,
  migration, or production-approval claim.

Gate 5.0 acceptance: `3 passed`; Gate 1–5 regression `606 passed, 173 subtests
passed`; migration head remains `e34d7a2c1b50`. Gate 5.1 is now current.

## Gate 5.1 — Protected Admin Shell + Read-only System/Platform Health

Status: PASS / CLOSED

### Implemented design

1. `/admin` is a dependency-free HTML health page and `/admin/health` is its
   JSON counterpart. Both require server-side HTTP Basic credentials.
2. Missing credentials fail closed with `503`; invalid or absent credentials
   receive `401` with a Basic challenge. There is no anonymous fallback.
3. Both endpoints reuse the existing API/worker heartbeat and persisted
   platform-health snapshot. Rendered values are HTML-escaped.
4. The surface is read-only: no platform toggle, notification action, user
   inquiry, or database mutation is exposed.

### Browser acceptance

On 2026-08-20, an authenticated operator opened the health page and saw all four
platform rows. The API rendered `HEALTHY`; the worker indicator rendered `False`
from its actual heartbeat rather than being hidden or rewritten. See
[reports/gate51_admin_health.md](reports/gate51_admin_health.md).

### Gate 5.1 acceptance

- Gate 5: `7 passed`;
- Gate 1–5 regression: `611 passed, 173 subtests passed`;
- migration head: `e34d7a2c1b50`;
- protected browser health page: `PASS`;
- no administrative write, provider call, notification send, live-truth
  mutation, Gate 0A closure, or production approval is claimed.

Gate 5.2 is now current.

## Gate 5.2 — Audited Platform Enable/Disable Controls

Status: PASS / CLOSED

### Implemented design

1. Only Bilibili, Douyin, Douyu, and Huya have protected Admin control routes.
   Arbitrary and synthetic platform names are rejected.
2. A disable action sets the platform health state to `DISABLED`. A restore
   action sets it to cautious `DEGRADED`, requiring a later successful probe to
   recover to `HEALTHY`.
3. The locked health-row update and append-only `admin_platform_actions` audit
   record commit in the same database transaction.
4. The Admin page requires an explicit browser confirmation before posting a
   control. It exposes no notification or live-truth operation.

### Acceptance

An authenticated operator completed Bilibili `HEALTHY → DISABLED → DEGRADED`.
Both transitions and their audit entries were verified read-only in PostgreSQL.
See [reports/gate52_platform_controls.md](reports/gate52_platform_controls.md).

### Gate 5.2 acceptance

- Gate 5: `11 passed`;
- Gate 1–5 regression: `615 passed, 173 subtests passed`;
- migration head: `f52a9d1c4e81`;
- protected disable/restore and durable audit: `PASS`;
- no provider call, notification send, grant mutation, historical live-truth
  rewrite, Gate 0A closure, or production approval is claimed.

Gate 5.3 is now current.

## Gate 5.3 — Protected User, Subscription, and Delivery Inquiry

Status: PASS / CLOSED

### Implemented design

1. The protected `/admin/inquiry` page and its `/admin/users`,
   `/admin/subscriptions`, and `/admin/deliveries` JSON counterparts reuse the
   existing Admin authorization boundary.
2. Each listing uses a bounded keyset cursor and a maximum page size of 50;
   the browser cannot request an unbounded operational dump.
3. The inquiry projection deliberately excludes OpenID, notification template
   identifiers, canonical room URLs, and raw provider/delivery error text.
4. The routes are read-only. They do not alter a subscription, delivery,
   notification grant, live observation, or historical outcome.

### Browser acceptance

On 2026-08-20, an authenticated operator opened `/admin/inquiry` and verified
the paginated user summary plus subscription rows containing creator, streamer,
platform, enabled state, and timestamp. The rendered page did not disclose an
OpenID, raw delivery error, template identifier, or canonical room URL. See
[reports/gate53_admin_inquiry.md](reports/gate53_admin_inquiry.md).

### Gate 5.3 acceptance

- Gate 5: `15 passed`;
- Gate 1–5 regression: `618 passed, 173 subtests passed`;
- migration head: `f52a9d1c4e81`;
- protected browser inquiry and bounded, redacted query projections: `PASS`;
- no administrative write, provider call, notification send, grant mutation,
  historical live-truth rewrite, Gate 0A closure, or production approval is
  claimed.

Gate 5.4 is now current.

## Gate 5.4 — Metrics and Bounded Error Aggregation

Status: PASS / CLOSED

### Implemented design

1. Protected Admin metrics expose only aggregate platform health, delivery
   channel/state counts, and error-code counts.
2. Platform, channel, state, and error-code dimensions are each mapped to a
   fixed allow-list. Any unexpected persisted value is aggregated as `OTHER`.
3. No aggregate label can contain OpenID, creator name, canonical URL,
   delivery ID, or raw provider response text.
4. The JSON and HTML metrics routes are read-only and reuse the server-side
   Admin authorization boundary.

### Browser acceptance

On 2026-08-20, an authenticated operator opened `/admin/metrics/page` and saw
four platform 24-hour rows, delivery counts grouped by `WECHAT_SUBSCRIBE` and
state, and one unknown error bucket rendered as `OTHER`. See
[reports/gate54_admin_metrics.md](reports/gate54_admin_metrics.md).

### Gate 5.4 acceptance

- Gate 5: `18 passed`;
- Gate 1–5 regression: `621 passed, 173 subtests passed`;
- migration head: `f52a9d1c4e81`;
- protected browser aggregates with bounded dimensions: `PASS`;
- no administrative write, provider call, notification send, grant mutation,
  historical live-truth rewrite, Gate 0A closure, or production approval is
  claimed.

Gate 5.5 is now current.

## Gate 5.5 — Restart-safe Administrative End-to-end Acceptance

Status: PASS / CLOSED

### Acceptance

The controlled PostgreSQL probe created a fresh database engine, read every
Admin projection, disposed it to simulate process restart, and then repeated
the same reads with a second new engine. It recorded the migration head
`f52a9d1c4e81`, four persisted platform rows, and unchanged bounded inquiry
and metric row counts across the restart boundary.

The probe is strictly read-only: it makes no provider call or notification send
and performs no database write or live-truth mutation. See
[reports/gate55_admin_restart_acceptance.md](reports/gate55_admin_restart_acceptance.md).

### Gate 5 final acceptance

- Gate 5: `19 passed`;
- Gate 1–5 regression: `622 passed, 173 subtests passed`;
- migration head: `f52a9d1c4e81`;
- protected health, audited platform controls, bounded inquiry, bounded
  aggregates, and fresh-engine restart reads: `PASS`;
- Gate 0A remains `DEGRADED`; no production approval or exactly-once claim is
  made.

Gate 5 is PASS / CLOSED. The next project phase is V1 Alpha readiness, which
requires an explicit operational plan and must not be represented as production
approval.
