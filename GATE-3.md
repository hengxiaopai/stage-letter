# Gate 3 — Notification Engine

Status: PASS / CLOSED

## Gate 3.0 — Baseline / Gap Freeze

Status: PASS / CLOSED

Gate 2 closed with `498 passed, 173 subtests passed` and migration head
`b25d4e9c7a12`. The project ROADMAP names **Gate 3 — Notification Engine** as the
next formal phase.

Gate 3 is intentionally a **completion/reconciliation phase**, not a rewrite.
Gate 1.6 already landed and accepted a large part of the ROADMAP's notification
engine earlier than originally planned. Gate 3 must preserve that evidence and
fill only the remaining product/runtime gaps.

### Accepted notification foundation reused from Gate 1.6

The following are already formal and must not be reimplemented under new competing
semantics:

- canonical `LIVE_STARTED / TRANSITION` notification eligibility;
- event-time follower fan-out and durable logical delivery enqueue;
- optimistic `wechat_subscription_grants` ledger;
- logical delivery identity `(user_id, live_event_id, channel)`;
- durable delivery states and crash/restart recovery;
- stale `IN_FLIGHT -> AMBIGUOUS` with no blind resend;
- WeChat subscribe-message provider adapter and normalized outcomes;
- evidence-backed WeChat mappings including `0`, `40003`, `40037`, `43101`,
  `45009`, `40001`, and `42001`;
- atomic delivery finalization plus grant consumption;
- real WeChat provider acceptance (`errcode=0`) and mobile receipt evidence from
  Gate 1.6-5;
- no provider/worker/notification exactly-once claim.

The real Gate 1.6-5 message **must not be resent merely to re-prove Gate 3.0**.
Gate 3 may reuse the accepted evidence and add new real-provider acceptance only
when a genuinely new behavior requires it.

### Baseline facts in current code

1. `DeliveryChannel.WECHAT_SUBSCRIBE` is the accepted existing channel.
2. `NotificationEnqueueApplicationService` currently plans WeChat deliveries from
   follows/preferences plus a positive WeChat grant.
3. `WeChatNotificationRuntime` claims durable delivery state before provider I/O
   and uses the accepted atomic finalization path.
4. WeChat `40037` already normalizes to `CONFIG_BLOCKED + PRESERVE`; however a
   durable template-level disable registry/policy is not yet formalized.
5. `WeChatLiveStartMessage` already has an optional `page` field, but Gate 1.6 did
   not make notification click routing to an anchor-detail page a formal product
   contract.
6. There is no formal `IN_APP` delivery channel/fallback path yet.

### Remaining ROADMAP gaps

Gate 3 therefore owns these remaining capabilities:

- durable `IN_APP` fallback when WeChat cannot/should not deliver;
- grant exhaustion routing to in-app rather than silent notification loss;
- WeChat failure classes that require fallback without unsafe provider retry;
- durable template configuration state and independent template disable/enable;
- `40037` triggering template disable without disabling platform adapters;
- formal grant intake/reconciliation path for `wx.requestSubscribeMessage`
  acceptance results;
- notification read model / delivery history needed by the Mini Program;
- semantic click target contract for anchor detail; actual Mini Program navigation
  is verified in Gate 4 once the page exists.

### Frozen boundaries

1. **Notification failure never mutates live truth.** Delivery/fallback/template
   state cannot create/close `LiveSession` or `LiveEvent`.
2. **WeChat accepted is not user-read.** Provider acceptance, device receipt, click,
   and read/open are distinct evidence levels.
3. **No blind resend of AMBIGUOUS.** Existing Gate 1.6 crash semantics remain.
4. **Fallback is a different logical channel.** An in-app delivery may be created
   for the same `(user,event)` without pretending it is the same external WeChat
   attempt.
5. **Grant ledger is optimistic local evidence.** It is not provider truth.
6. **40037 is template/config scope.** It must not disable Douyin/Bilibili/Huya/
   Douyu detection adapters.
7. **Gate 0A remains DEGRADED.** Notification acceptance still cannot close the
   missing same-creator real-provider lifecycle evidence.
8. **Gate 2 remains frozen.** Gate 3 must not bypass detection/live-truth ingress.

### Gate 3 slices

- **3.0** Baseline / Gap Freeze. **PASS / CLOSED**
- **3.1** Multi-Channel Delivery + Durable In-App Fallback. **PASS / CLOSED**
- **3.2** WeChat Template Registry + 40037 Disable / Administrative Recovery. **PASS / CLOSED**
- **3.3** Grant Intake + Reconciliation + User-Facing Grant API. **PASS / CLOSED**
- **3.4** Notification Read Model + Anchor Detail Routing Contract. **PASS / CLOSED**
- **3.5** Restart / Fallback / End-to-End Notification Engine Acceptance. **PASS / CLOSED**

### Gate 3.0 acceptance

- Gate 1 + Gate 2 + Gate 3.0 boundary tests remain green.
- Existing WeChat/grant/delivery semantics are reused, not forked.
- Remaining ROADMAP gaps are explicit and mapped to one later slice each.
- Gate 3.0 performs no provider call and no real WeChat resend.
- Gate 3.0 adds no migration; expected head remains `b25d4e9c7a12`.
- No exactly-once or Gate 0A lifecycle claim is introduced.

Gate 3.0 acceptance: `7 / 7 PASS`; Gate 1 + Gate 2 + Gate 3 regression
`505 / 505 PASS`; migration head `b25d4e9c7a12`.

## Gate 3.1 — Multi-Channel Delivery + Durable In-App Fallback

Status: PASS / CLOSED

### Accepted design

1. `DeliveryChannel.IN_APP` is a formal channel. Its logical identity remains
   `(user_id, live_event_id, channel)`, so it is distinct from the corresponding
   `WECHAT_SUBSCRIBE` delivery and durably idempotent under the existing unique
   constraint.
2. Multi-channel enqueue prefers `WECHAT_SUBSCRIBE` only while the optimistic
   local grant ledger has positive availability. Missing or exhausted grant
   evidence routes directly to `IN_APP`; it is no longer silent notification
   loss.
3. An active WeChat retry remains `WAITING_RETRY` without premature fallback.
   `WAITING_AUTH`, `BLOCKED_CONFIG`, `FAILED_TERMINAL`, and `AMBIGUOUS` require a
   separate durable `IN_APP` fallback. Retry exhaustion first becomes
   `FAILED_TERMINAL`, then follows the same fallback rule.
4. `AMBIGUOUS` still never permits a blind WeChat resend. Creating a different
   internal channel does not reinterpret the external result as failed or
   accepted.
5. WeChat due-selection and restart recovery are restricted to
   `WECHAT_SUBSCRIBE`. The in-app publisher selects only `IN_APP`, completes its
   DB-only transition atomically, and performs no provider I/O.
6. The old `workers/notify/in_app.py` lowercase-channel implementation remains
   legacy reference code. It is not imported into the formal Gate 3.1 path.

### Gate 3.1 acceptance

- grant available -> one durable `WECHAT_SUBSCRIBE` delivery;
- grant missing/exhausted -> one durable `IN_APP` delivery;
- terminal/blocked/auth/ambiguous WeChat outcomes -> idempotent `IN_APP`
  fallback for the same user/event;
- active retry and accepted WeChat outcomes do not create fallback;
- channel-scoped workers cannot claim the other channel;
- in-app publication performs no external provider call;
- notification work does not import or mutate live-truth persistence services;
- Gate 1 + Gate 2 + Gate 3 regression remains green;
- no schema change is required because the existing channel column and
  `(user_id, live_event_id, channel)` unique key already support `IN_APP`;
  expected migration head remains `b25d4e9c7a12`.

Gate 3.1 acceptance: Gate 3 `20 passed`; Gate 1 + Gate 2 + Gate 3
`518 passed, 173 subtests passed`; migration head `b25d4e9c7a12`. No provider
request or live-truth mutation was performed by the Gate 3.1 acceptance suite.

## Gate 3.2 — WeChat Template Registry + Administrative Recovery

Status: PASS / CLOSED

### Accepted design

1. `wechat_notification_templates` is durable notification configuration state,
   not live truth and not part of the frozen Gate 1 canonical `Base`.
2. A missing registry row is compatibly treated as enabled so the migration does
   not silently disable the already accepted Gate 1.6 template. Registration is
   explicit and never re-enables an existing disabled row.
3. Template state is `ENABLED` or `DISABLED`, with durable `state_source`,
   `updated_by`, `updated_at`, and internally consistent disable metadata.
4. Only normalized WeChat provider code `40037` automatically disables the
   template. The template-state write and delivery `BLOCKED_CONFIG` finalization
   share one database transaction; the optimistic grant remains preserved.
5. A disabled template affects only `WECHAT_SUBSCRIBE`. New fan-out routes to
   `IN_APP`; already queued WeChat delivery is blocked before provider I/O and
   creates the Gate 3.1 fallback.
6. Recovery is explicit through `enable_by_administrator` or
   `scripts/gate32_template_admin.py enable`. Registration, retries, process
   restart, and successful detection never auto-enable a disabled template.
7. Template disable cannot disable Douyin, Bilibili, Huya, or Douyu adapters and
   cannot create/close `LiveSession` or `LiveEvent`.

### Gate 3.2 acceptance

- migration extends `b25d4e9c7a12` with durable constrained template state;
- PostgreSQL observes register -> provider `40037` disable -> restart read ->
  administrator enable across independent transactions;
- `40037` finalization disables only its exact template and preserves grant;
- non-`40037` provider outcomes do not change template state;
- disabled templates route new recipients to `IN_APP` even with grant balance;
- queued WeChat work is blocked before address lookup/provider I/O;
- administrative enable clears disable metadata and records administrator source;
- controlled probe performs no provider call, notification send, or live mutation,
  and removes its synthetic template row;
- Gate 1 + Gate 2 + Gate 3 regression remains green.

Gate 3.2 acceptance: Gate 3 `32 passed`; Gate 1 + Gate 2 + Gate 3
`530 passed, 173 subtests passed`; migration head `c32a1d7e9b40`; controlled
PostgreSQL registry probe `PASS` with `cleanup_complete=true` and
`database_restored=true`. No provider request or notification send was made.

## Gate 3.3 — Grant Intake + Reconciliation + User-Facing Grant API

Status: PASS / CLOSED

### Accepted design

1. The Mini Program sends the exact per-template result returned by
   `wx.requestSubscribeMessage`: `accept`, `reject`, or `ban`. It can no longer
   submit an arbitrary aggregate `accept_count`.
2. Each client callback carries a client-generated `request_id`.
   `wechat_grant_intakes` durably keys evidence by
   `(user_id, request_id, template_id)`: an exact replay is idempotent, while a
   changed decision for the same key is rejected and the transaction rolls back.
3. A newly recorded `accept` atomically increments the optimistic ledger by
   exactly one. `reject` and `ban` are evidence only; they never consume or erase
   an earlier grant.
4. Intake is not provider truth. WeChat exposes no server-side grant-balance
   query used by this project. Existing provider send outcomes remain the
   authoritative reconciliation input for `consumed_count` through the Gate 1.6
   atomic finalizer.
5. The user-facing read returns `available=max(0, granted-consumed)` and exposes
   `ledger_drift_detected` when provider-authoritative consumption exceeds local
   intake evidence. It never fabricates a negative user balance.
6. V1 accepts only the configured live-start template at the public API boundary,
   and requires an existing logged-in user. The current direct `openid` query is
   still explicitly a development identity seam; production token hardening is
   not claimed by Gate 3.3.
7. `wechat_grant_intakes` is notification operational evidence outside the
   frozen Gate 1 canonical `Base`. It cannot create/close live sessions/events.

### Gate 3.3 acceptance

- PostgreSQL observes new accept -> `+1`, exact replay -> no increment,
  reject -> evidence only, changed-decision replay -> conflict/rollback;
- a newly composed service after transaction restart reads the same durable
  ledger and intake evidence;
- the controlled probe deletes its synthetic intake, grant, and user rows;
- public API and Mini Program contracts carry `request_id` plus exact decisions,
  with no `accept_count` input;
- migration extends `c32a1d7e9b40` with a constrained evidence table while the
  canonical Base stays frozen;
- no provider request, notification send, provider-balance query, live mutation,
  or exactly-once claim is performed.

Gate 3.3 acceptance: Gate 3 `40 passed`; Gate 1 + Gate 2 + Gate 3
`538 passed, 173 subtests passed`; migration head `d33c4e8a1b60`; controlled
PostgreSQL grant-intake probe `PASS` with `cleanup_complete=true` and
`database_restored=true`.

## Gate 3.4 — Notification Read Model + Anchor Detail Routing Contract

Status: PASS / CLOSED

### Accepted design

1. Notification history reads formal `notification_deliveries` joined to formal
   event, session, platform-account, and creator-profile context. It no longer
   depends on legacy `notification_jobs` or creates a user as a GET side effect.
2. Pagination is newest-first keyset pagination on durable delivery identity.
   The cursor is the last visible delivery id; no offset cursor can duplicate or
   skip rows merely because newer notifications arrive.
3. `idx_g34_delivery_user_history (user_id, id)` supports the user-scoped
   keyset query. No parallel notification-history table or canonical entity is
   introduced.
4. One `AnchorDetailTarget` owns both
   `pages/detail/index?id={anchor_id}` and `/api/v1/anchors/{anchor_id}`. The
   history API, Mini Program notification row, and WeChat subscribe-message
   `page` field use that same semantic target.
5. The existing anchor-detail API keeps its legacy Anchor behavior and adds a
   read-only formal Creator fallback. A missing open session remains UNKNOWN;
   it is never fabricated as OFFLINE.
6. Provider acceptance, device receipt, Mini Program click, and detail-page read
   remain distinct evidence. Gate 3.4 wires and tests the routing contract but
   does not claim a real device click or user read; that UI acceptance belongs to
   Gate 4.

### Gate 3.4 acceptance

- PostgreSQL returns three synthetic formal deliveries newest-first over two
  keyset pages without duplicates;
- creator profile and platform metadata are joined from formal tables;
- both legacy-mirrored and formal-only Creator ids resolve through the same
  anchor-detail endpoint;
- WeChat message construction populates the same Mini Program detail path;
- Mini Program history rows accept only the detail-path contract before
  navigation;
- controlled probe performs no provider request, notification send, live-truth
  mutation, or user-read claim and removes all synthetic rows;
- Gate 1 + Gate 2 + Gate 3 regression remains green.

Gate 3.4 acceptance: Gate 3 `48 passed`; Gate 1 + Gate 2 + Gate 3
`546 passed, 173 subtests passed`; migration head `e34d7a2c1b50`; controlled
PostgreSQL notification-history probe `PASS` with `cleanup_complete=true`,
`formal_detail_target_resolves=true`, and `database_restored=true`.

## Gate 3.5 — Restart / Fallback / End-to-End Acceptance

Status: PASS / CLOSED

### Accepted end-to-end behavior

1. One formal `LIVE_STARTED / TRANSITION` event fans out by persisted follow,
   preference, template, and optimistic grant evidence. A user without grant
   receives `IN_APP`; a user with grant receives `WECHAT_SUBSCRIBE`.
2. Concurrent WeChat workers use durable row locking and only one claims a
   logical delivery. This is a single-winner database claim, not a claim that
   workers or external providers execute exactly once.
3. A process restart observing stale `IN_FLIGHT` resolves it to `AMBIGUOUS` and
   never returns it to blind provider retry.
4. `WAITING_AUTH`, `BLOCKED_CONFIG`, `FAILED_TERMINAL`, and `AMBIGUOUS` create one
   separate durable `IN_APP` fallback. Reconciliation/restart replay reuses the
   same fallback identity.
5. The DB-only in-app runtime publishes pending fallback/direct deliveries to
   `SENT`, after which the Gate 3.4 history read model exposes both the original
   WeChat outcome and the internal fallback with the same anchor-detail target.
6. No-provider acceptance preserves the optimistic grant ledger. It cannot
   consume a grant or claim provider acceptance without an actual send result.
7. Notification execution never creates/closes live sessions or events. Provider
   acceptance, device receipt, click, and user read remain separate evidence.

### Gate 3.5 acceptance

- controlled PostgreSQL fan-out creates exactly one channel choice for each of
  two synthetic users from the same canonical event;
- two independent workers race for WeChat work and exactly one database claim
  wins;
- an independently composed restart worker recovers one stale delivery as
  `AMBIGUOUS`, then fallback creation is idempotent;
- two in-app deliveries become `SENT` and a third run is `IDLE`;
- notification history exposes the direct in-app path and the
  WeChat-ambiguous-plus-fallback path without duplicates;
- grant remains `1 granted / 0 consumed` because no provider call occurred;
- the canonical session remains open and exactly one live event remains;
- all synthetic users, follows, preferences, grants, deliveries, event, session,
  account, profile, and creator are removed;
- no migration is added; expected head remains `e34d7a2c1b50`.

Gate 3.5 acceptance: Gate 3 `58 passed`; Gate 1 + Gate 2 + Gate 3
`556 passed, 173 subtests passed`; migration head `e34d7a2c1b50`; controlled
PostgreSQL restart/fallback/E2E probe `PASS` with
`multiworker_single_claim_winner=true`, `restart_recovered_one_ambiguous=true`,
`live_truth_preserved=true`, and `database_restored=true`.

## Gate 3 Closure

Gate 3 is **PASS / CLOSED**. Gate 4.0 — Mini Program Baseline / Product-Flow
Reconciliation is now current. Gate 4 must reuse the accepted backend contracts,
perform real WeChat Developer Tools/device interaction where required, and must
not reopen notification truth merely for UI redesign.
