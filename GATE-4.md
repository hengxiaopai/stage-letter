# Gate 4 — WeChat Mini Program

Status: PASS / CLOSED

## Gate 4.0 — Baseline / Product-Flow Gap Freeze

Status: PASS / CLOSED

Gate 3 closed with `556 passed, 173 subtests passed`, migration head
`e34d7a2c1b50`, and a controlled PostgreSQL notification E2E PASS. Gate 4 reuses
those accepted detection and notification contracts. It owns real Mini Program
interaction; it does not reopen backend truth semantics merely to redesign UI.

### Accepted foundation reused from Gate 1–3

- four platform adapters and the formal `LIVE / OFFLINE / UNKNOWN` truth boundary;
- HOT / WARM / COLD scheduling, PostgreSQL leases, and platform capacity isolation;
- durable `WECHAT_SUBSCRIBE` and `IN_APP` notification channels;
- optimistic grant intake/reconciliation and template-level `40037` disable;
- notification history plus the canonical `pages/detail/index?id={anchor_id}` target;
- restart recovery and the rule that `AMBIGUOUS` is never blindly resent;
- no worker, provider, delivery, click, or read exactly-once claim.

### Baseline facts in current Mini Program

1. `miniapp/` is a native WXML / WXSS / JavaScript project. Gate 4 will not migrate
   it to Taro or introduce a competing frontend application.
2. The four ROADMAP surfaces already exist: home, add subscription,
   subscriptions, and profile. Anchor detail is a fifth routed page supporting
   notification/history navigation.
3. Pages use the existing `/api/v1` services for active live state, anchor search,
   subscriptions, grant intake, notification history, and anchor detail.
4. The add and profile flows call `wx.requestSubscribeMessage` and submit exact
   per-template results through the Gate 3.3 intake contract.
5. Notification history accepts only the Gate 3.4 anchor-detail path before
   calling `wx.navigateTo`; this is a static routing contract, not device-click
   evidence.
6. At the Gate 4.0 baseline, `miniapp/services/auth.js` still returned a fixed
   `DEV_OPENID` before `wx.login`. Therefore real WeChat login was not yet
   accepted, even though both the client `wx.login` branch and server
   `/auth/login` code2session route already existed.
7. The current public API still passes raw `openid` as a development identity
   seam. Gate 4.1 must make the client login path real and explicitly freeze the
   remaining production-token limitation rather than silently claiming it solved.
8. The live-start template identifier is duplicated in page code. Later UI work
   must use one client configuration source without exposing AppSecret or other
   credentials.

### Remaining product-flow gaps

- real `wx.login -> /auth/login -> code2session` execution in WeChat Developer Tools;
- stable client login state, visible failure/retry behavior, and no fixed-user bypass;
- four core pages verified against the accepted backend APIs without mock truth;
- paste-link subscription plus grant intake verified as one user-driven flow;
- notification tap opening the same anchor detail on a real device;
- loading, empty, degraded, permission-denied, and network-error UX acceptance;
- Developer Tools and phone evidence for the complete login-to-detail journey.

### Frozen boundaries

1. **UI never invents live truth.** `UNKNOWN`, detection failure, and stale data
   cannot be rendered as confirmed `OFFLINE`.
2. **Permission is user-driven.** `wx.requestSubscribeMessage` may run only from a
   user action; no background replay or fabricated grant is allowed.
3. **Provider accepted is not device receipt, click, or read.** Gate 4 must label
   each evidence level accurately.
4. **Secrets stay server-side.** AppSecret, database credentials, access tokens,
   session keys, and user identifiers must not be embedded in Mini Program code,
   screenshots, logs, or committed private configuration.
5. **Gate 3 contracts are reused.** The Mini Program does not create a second
   notification ledger, history model, or detail-target format.
6. **Gate 0A remains DEGRADED.** UI or device acceptance cannot fill missing
   same-creator platform lifecycle evidence.
7. **No production approval is implied.** Developer Tools and controlled-device
   acceptance are necessary but not sufficient for production release.

### Gate 4 slices

- **4.0** Baseline / Product-Flow Gap Freeze. **PASS / CLOSED**
- **4.1** WeChat Login + Client Identity Boundary. **PASS / CLOSED**
- **4.2** Core Page API Integration + State UX. **PASS / CLOSED**
- **4.3** Paste-Link Subscription + Grant Permission Journey. **PASS / CLOSED**
- **4.4** Notification Tap + Anchor Detail Journey. **PASS / CLOSED**
- **4.5** Developer Tools / Device E2E + Mini Program Acceptance. **PASS / CLOSED**

### Gate 4.0 acceptance

- Gate 4 boundary tests pass without calling WeChat, providers, or PostgreSQL.
- Existing native pages and accepted Gate 3 client contracts are inventoried.
- Fixed `DEV_OPENID`, raw-openid development identity, and duplicated template
  configuration are recorded as gaps, not accepted production behavior.
- Real Developer Tools/device evidence is assigned to later slices and is not
  replaced by source-string or route-shape tests.
- Gate 1–3 regression remains green.
- No migration is added; expected head remains `e34d7a2c1b50`.
- No live-truth mutation, notification send, grant fabrication, device-click,
  user-read, exactly-once, Gate 0A closure, or production claim is introduced.

Gate 4.0 acceptance: `7 / 7 PASS`; Gate 1–4 regression
`563 passed, 173 subtests passed`; migration head `e34d7a2c1b50`. The acceptance
suite made no provider request, notification send, database write, device-click,
or user-read claim. Gate 4.1 is now current.

## Gate 4.1 — WeChat Login + Client Identity Boundary

Status: PASS / CLOSED

### Accepted design

1. The Mini Program always starts identity acquisition with `wx.login`; there is
   no fixed `DEV_OPENID` or other source-level user bypass.
2. The client sends the one-time code only to `POST /api/v1/auth/login`. It keeps
   the returned openid in App memory for the current process and does not persist
   it with `wx.setStorage`.
3. `App.ensureLogin()` is single-flight. Concurrent pages share one pending login,
   a successful identity uses the in-memory fast path, and failure clears the
   pending promise so a later user/page action can retry.
4. The API trims and validates the code, performs WeChat `code2session`, and
   creates or reuses the matching user. Empty, blank, and oversized codes never
   reach WeChat.
5. Missing server WeChat configuration returns `503`; WeChat transport failure
   returns retryable `503`; invalid or expired code returns `400`. None of these
   paths fabricate an openid, even when `DEBUG=true`.
6. Raw openid remains an explicitly documented development identity seam. Gate
   4.1 does not claim bearer-token hardening, device receipt, notification click,
   user read, exactly-once delivery, or production approval.

### Developer Tools acceptance

On 2026-08-20, WeChat Developer Tools Stable `1.06.2504010` recompiled the current
Mini Program with zero compile errors. The simulator rendered the home page after
login. The Network panel observed HTTP `200` for `login`, followed by `active`,
`subscriptions`, and `refresh`; no login code or openid was copied into the
acceptance record. Details are in [reports/gate41_wechat_login.md](reports/gate41_wechat_login.md).

### Gate 4.1 acceptance

- no fixed client identity or persisted raw openid;
- real `wx.login -> /auth/login -> code2session` succeeds in Developer Tools;
- first-time user creation and existing-user reuse are covered independently;
- invalid input, missing configuration, invalid code, and transport failure are
  visible errors rather than fake login success;
- Gate 4 automated tests and Gate 1–4 cumulative regression remain green;
- no migration is added; expected head remains `e34d7a2c1b50`;
- no AppSecret, login code, openid, provider request, notification send,
  device-click, or user-read evidence is stored by the acceptance suite.

Gate 4.1 acceptance: Gate 4 `16 passed`; Gate 1–4 regression
`572 passed, 173 subtests passed`; migration head `e34d7a2c1b50`; Developer Tools
compile `PASS`, login HTTP `200`, and dependent home reads HTTP `200`. Gate 4.2 is
now current.

## Gate 4.2 — Core Page API Integration + State UX

Status: PASS / CLOSED

### Accepted design

1. The shared Mini Program request layer raises `ApiError` with a stable
   `statusCode`. Pages can distinguish transport failure (`0`), missing data
   (`404`), validation failure, and server failure without parsing message text.
2. Home, subscriptions, profile, and detail expose loading, visible error, and
   explicit retry states. A retry clears stale error UI before issuing the same
   accepted read again.
3. Profile no longer turns a failed grants/history request into a false empty
   notification history or a fabricated zero-balance success state.
4. Detail renders confirmed `OFFLINE` separately from `UNKNOWN`, `DEGRADED`, and
   confirmation states. Uncertain live truth says that status cannot currently be
   confirmed and that detection will retry; it never says the creator is offline.
5. Subscription deletion reconciles HTTP `404` as already removed by structured
   status, not English error-message matching. Local live count uses the same
   formal `isLiveFlag` as sorting and display.
6. Pull-to-refresh remains available on the three core tab pages, while search,
   permission, subscription, and notification side effects remain user-driven.

### Developer Tools acceptance

On 2026-08-20, the current Mini Program recompiled in WeChat Developer Tools and
rendered home, subscriptions, profile, and add-subscription surfaces. Login and
all page reads observed during this pass returned HTTP `200`. The inspected user
had no subscriptions, so no detail-row navigation was fabricated; real detail
click acceptance remains assigned to Gate 4.4. See
[reports/gate42_core_page_states.md](reports/gate42_core_page_states.md).

### Gate 4.2 acceptance

- structured API error status is preserved through the page boundary;
- load failures are visible and retryable instead of silently becoming empty data;
- uncertain detection state is never rendered as confirmed offline;
- subscription 404 reconciliation and post-delete live count use formal fields;
- native WXML / WXSS / JavaScript remains the only Mini Program implementation;
- Gate 4 tests and Gate 1–4 cumulative regression remain green;
- no migration is added; expected head remains `e34d7a2c1b50`;
- no search, subscription, grant permission, cancellation, notification send,
  device-click, or user-read action was performed for this acceptance.

Gate 4.2 acceptance: Gate 4 `23 passed`; Gate 1–4 regression
`579 passed, 173 subtests passed`; migration head `e34d7a2c1b50`; Developer Tools
compile/page rendering `PASS`. Gate 4.3 is now current.

## Gate 4.3 — Paste-Link Subscription + Grant Permission Journey

Status: PASS / CLOSED

### Implemented design

1. The server supplies the public live-start template identifier in the login
   response. The Mini Program keeps it in App memory, so pages no longer duplicate
   a template literal. AppSecret and other credentials remain server-side.
2. `wx.requestSubscribeMessage` is called only from an explicit user handler and
   only when the server supplied a template identifier. Its exact per-template
   result is submitted through the existing Gate 3 grant-intake contract.
3. Accept, reject, ban, missing-template, and permission-request failure are
   recorded separately from following a creator. Once the user confirms the
   follow action, permission denial does not block creation of the subscription:
   durable `IN_APP` fallback remains available under the accepted Gate 3 policy.
4. An accepted permission result selects WeChat as the preferred reminder path;
   all other results clearly tell the user that the subscription was created with
   in-app reminders. No client grant is fabricated when WeChat did not return
   `accept`.
5. Raw openid remains the Gate 4.1 development identity seam. This slice does not
   claim production identity hardening, provider delivery, device receipt, click,
   read, or exactly-once behavior.

### Automated and Developer Tools evidence

- Gate 4.3 boundary tests cover server configuration handoff, in-memory client
  configuration, removal of page-level template literals, exact permission-result
  intake, user-handler-only invocation, and permission-independent subscription.
- Gate 4 tests pass with `31 passed`; Gate 1–4 cumulative regression passes with
  `587 passed, 173 subtests passed`.
- JavaScript syntax checks pass for App, auth service, add, and profile code.
- WeChat Developer Tools recompiled the Mini Program, rendered home, and opened
  `pages/add/index`; login and dependent reads observed in Network returned HTTP
  `200`.
- No migration is added; expected head remains `e34d7a2c1b50`.

### Real Developer Tools acceptance

On 2026-08-20, an explicitly authorized acceptance used the Bilibili creator URL
`https://space.bilibili.com/299312132` in WeChat Developer Tools. URL parsing
returned a confirmed creator card. The first subscription attempt exposed a real
compatibility defect: the legacy route did not populate Gate 1's non-null formal
`creator_id`, so PostgreSQL correctly rejected the write. The route was repaired
to keep Creator/Profile, PlatformAccount, Follow, NotificationPreference,
Anchor, and UserSubscription in one compatibility transaction. A controlled
diagnostic write passed and its eight dedicated rows were removed before the
real retry.

The authorized retry returned HTTP `200` with a valid subscription response.
Read-only PostgreSQL verification confirmed the legacy identity bridge, formal
Creator/Profile, formal Follow, and enabled NotificationPreference. Developer
Tools produced no durable grant intake or accepted grant in this run, so the
accepted Gate 3 policy selected `IN_APP` fallback; no WeChat grant was fabricated.
No openid, template identifier, login code, AppSecret, access token, or database
credential is stored in this evidence. See
[reports/gate43_subscription_permission.md](reports/gate43_subscription_permission.md).

Gate 4.3 acceptance: Gate 4 `31 passed`; Gate 1–4 regression
`587 passed, 173 subtests passed`; migration head `e34d7a2c1b50`; paste-link
parse `PASS`; subscription HTTP `200`; formal/legacy persistence bridge `PASS`;
fallback `IN_APP`. Gate 4.4 is now current.

## Gate 4.4 — Notification Tap + Anchor Detail Journey

Status: PASS / CLOSED

### Implemented design

1. Notification history routes through the formal Gate 1 Creator identity. The
   server emits one canonical `pages/detail/index?id=<positive creator id>` target;
   the client accepts only that exact path and rejects suffix injection or invalid
   identities before navigation.
2. The detail page validates the positive creator identity before issuing its API
   read. Invalid or missing identities produce a visible error instead of an
   accidental request.
3. The initial notification-history request omits the optional keyset cursor.
   Pagination cursors remain opaque server values; the client no longer invents
   offset-like `cursor=0`.
4. Notification rows remain user-driven navigation. This slice does not mark a
   notification read, send a provider message, consume a grant, or claim device
   receipt.

### Developer Tools acceptance

On 2026-08-20, WeChat Developer Tools loaded the existing profile notification
history from PostgreSQL. The first pass exposed the invalid initial cursor and
returned HTTP `422`; the client contract was repaired and the retry loaded the
existing history successfully. Clicking the existing notification row navigated
to `pages/detail/index`, the anchor-detail API returned HTTP `200`, and the page
rendered the corresponding creator and live-session state. No fixture, notification
send, grant intake, provider call, or database write was created for this click
acceptance. See
[reports/gate44_notification_detail.md](reports/gate44_notification_detail.md).

### Gate 4.4 acceptance

- precise Gate 4.4 tests: `11 passed`;
- Gate 4 tests: `42 passed`;
- Gate 1–4 regression: `598 passed, 173 subtests passed`;
- migration head unchanged: `e34d7a2c1b50`;
- Developer Tools existing-history load and detail navigation: `PASS`;
- provider send, device receipt, user-read mutation, and production approval are
  not claimed.

## Gate 4.5 — Developer Tools / Device E2E + Mini Program Acceptance

Status: PASS / CLOSED

### Accepted evidence

1. WeChat Developer Tools recompiled the native client and verified the home,
   subscriptions, profile, and add-subscription pages against the local API.
   Component-WXSS selector and `scroll-view` flex warnings found in this pass
   were repaired with focused regression coverage.
2. A user-driven WeChat subscription-message acceptance reached the durable
   grant intake; no grant was fabricated or silently replayed.
3. A disabled, isolated account generated one canonical controlled
   `LIVE_STARTED / TRANSITION` event after the corresponding follow timestamp.
4. WeChat accepted one controlled delivery (`errcode=0`); its durable state was
   `SENT`, exactly one grant was consumed, and that state persisted across a
   fresh runtime/database read.
5. The phone received the corrected developer-version message and the user
   tapped it into the canonical anchor-detail page. The controlled sender now
   includes `pages/detail/index?id=<positive creator id>` and uses the uploaded
   developer Mini Program state rather than an unpublished formal release.

### Gate 4.5 acceptance

- Gate 4: `47 passed`;
- Gate 1–4 regression: `603 passed, 173 subtests passed`;
- migration head: `e34d7a2c1b50`;
- provider acceptance, physical-device receipt, and user-driven detail click:
  `PASS`;
- no user-read mutation, exactly-once claim, Gate 0A closure, or production
  approval is claimed.

See [reports/gate45_device_e2e.md](reports/gate45_device_e2e.md).

Gate 4 is now PASS / CLOSED. Gate 5 is now current.
