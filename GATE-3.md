# Gate 3 — Notification Engine

## Gate 3.0 — Baseline / Gap Freeze

Status: CURRENT

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

- **3.0** Baseline / Gap Freeze. **CURRENT**
- **3.1** Multi-Channel Delivery + Durable In-App Fallback.
- **3.2** WeChat Template Registry + 40037 Disable / Administrative Recovery.
- **3.3** Grant Intake + Reconciliation + User-Facing Grant API.
- **3.4** Notification Read Model + Anchor Detail Routing Contract.
- **3.5** Restart / Fallback / End-to-End Notification Engine Acceptance.

### Gate 3.0 acceptance

- Gate 1 + Gate 2 + Gate 3.0 boundary tests remain green.
- Existing WeChat/grant/delivery semantics are reused, not forked.
- Remaining ROADMAP gaps are explicit and mapped to one later slice each.
- Gate 3.0 performs no provider call and no real WeChat resend.
- Gate 3.0 adds no migration; expected head remains `b25d4e9c7a12`.
- No exactly-once or Gate 0A lifecycle claim is introduced.
