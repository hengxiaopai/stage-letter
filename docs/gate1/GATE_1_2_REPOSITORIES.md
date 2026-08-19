# Gate 1.2-2 — SQLAlchemy Repository Implementations

Status: **PASS**

Entry authority: Gate 1.2-1 PASS.

## 1. Purpose

Gate 1.2-2 implements the four persistence ports frozen in Gate 1.1:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
```

Formal implementations live under:

```text
stage_letter/infrastructure/db/repositories/
```

Repositories translate persistence rows to/from formal domain objects. They do
not own live-state transitions, notification eligibility, provider behavior, or
transaction commits.

## 2. Identity contract — PASS

Formal domain/application identifiers are strings, while PostgreSQL retains
BIGINT primary keys for users, creators, platform accounts, and live sessions.

Frozen translation:

```text
User.user_id                 <-> users.id BIGINT
Creator.creator_id           <-> creators.id BIGINT
PlatformAccount.account_id   <-> platform_accounts.id BIGINT
LiveSession.session_id       <-> live_sessions.id BIGINT
```

Only canonical positive ASCII decimal strings are accepted for BIGINT-backed
identities. Hashing, truncation, generated substitutes, signs, whitespace,
leading-zero aliases, Unicode digits, zero, negatives, and out-of-range values
are rejected.

Accepted evidence:

```text
Repository identity tests: 7 / 7 PASS
Full Gate 1 suite:          69 / 69 PASS
```

Formal evidence identities remain native strings and are persisted verbatim:

```text
LiveObservation.observation_id -> live_observations.observation_id
LiveEvent.event_id              -> live_events.event_id
DeliveryKey.live_event_id       -> LiveEvent.event_id semantic identity
```

## 3. Source-scoped observation identity correction

The formal LiveRepository port was narrowed from ambiguous
`has_observation(observation_id)` to:

```text
has_observation(account_id, source, observation_id)
```

This matches the already accepted durable uniqueness:

```text
(platform_account_id, source, observation_id)
```

No Gate 0 live-truth semantic changed.

## 4. Legacy write bridge — PASS

Forward-only revision:

```text
c91e8d2f4a10_gate12_relax_legacy_write_bridges.py
```

Revision chain:

```text
...
-> b63e4f9a1c20
-> c91e8d2f4a10
```

The revision allows new formal rows to leave obsolete legacy-only facts unknown
instead of fabricating them. Existing legacy facts are preserved.

Relaxed legacy requirements include:

```text
platform_accounts.anchor_id
platform_accounts.last_status
platform_accounts.polling_tier
platform_accounts.canonical_url
live_sessions.anchor_id
live_sessions.platform
live_sessions.state
live_sessions.started_at_source
live_events.anchor_id
live_events.confidence
live_events.detected_at
notification_deliveries.notification_job_id
```

The obsolete session-keyed delivery uniqueness was removed after Gate 1.1 had
already established canonical event-keyed idempotency:

```text
(user_id, live_event_id, channel)
```

## 5. Repository implementations — PASS

Accepted implementations:

```text
stage_letter/infrastructure/db/repositories/common.py
stage_letter/infrastructure/db/repositories/creator.py
stage_letter/infrastructure/db/repositories/follow.py
stage_letter/infrastructure/db/repositories/live.py
stage_letter/infrastructure/db/repositories/notification.py
```

Frozen behavior:

```text
CreatorRepository
  creator/profile/account read + save
  preserves existing legacy bridge evidence

FollowRepository
  Follow and NotificationPreference remain separate

LiveRepository
  source-scoped observation identity
  durable idempotent observation append
  open session uses ended_at IS NULL
  event/session origin/cause is never invented

NotificationRepository
  resolves formal LiveEvent.event_id to DB event row
  logical identity = user/event/channel
  PostgreSQL race-safe create-if-absent
  no fabricated notification_job_id
```

All repository methods use the supplied AsyncSession and contain no independent
`commit()`/`rollback()`, provider/network call, state-machine decision,
notification eligibility rule, legacy runtime import, or UNKNOWN->OFFLINE
reclassification.

## 6. Real PostgreSQL acceptance — PASS

Accepted user-local probe:

```text
[gate12] database created
[gate12] seeded at Gate 1.1 head -> b63e4f9a1c20
[gate12] bridge migration PASS -> c91e8d2f4a10
PASS: Gate 1.2-2 SQLAlchemy repositories + legacy write bridge
[cleanup] dropped stageletter_gate12_repo
```

It proved the forward bridge, preservation of representative legacy facts, new
formal writes with NULL obsolete bridges, all four repository read/write paths,
source-scoped observation idempotency, event-keyed delivery idempotency, and
isolated DB cleanup.

The first probe attempt was blocked only by direct-script Python module-path
bootstrap. The harness was corrected before the successful run; it was not a
repository/migration semantic failure.

## 7. Final static acceptance — PASS

Accepted user-local evidence after the repository/bridge changes:

```text
Ran 78 tests in 0.444s
OK

c91e8d2f4a10 (head)

PASS: Gate 1.2 offline SQL compilation
```

The 78-test suite includes the formal boundary contracts and repository
implementation contracts, so the earlier dependency freeze remains green.

## 8. Acceptance result

```text
A. Gate 1.2-1 remains PASS                                  PASS
B. persistence identity contract frozen                     PASS
C. identity contract tests pass                             PASS / 7/7
D. legacy write-bridge strategy implemented safely          PASS
E. CreatorRepository implements port                        PASS
F. FollowRepository implements port                         PASS
G. LiveRepository implements port                           PASS
H. NotificationRepository uses event-key identity           PASS
I. repositories never commit independently                  PASS
J. repository tests against PostgreSQL pass                 PASS
K. full Gate 1 suite remains green                          PASS / 78/78
L. formal boundary AST tests remain green                   PASS / included in 78/78
M. Alembic head == c91e8d2f4a10                            PASS
N. UTF-8 offline SQL compilation through new head           PASS
```

Gate 1.2-2: **PASS**.

Next: Gate 1.2-3 — SQLAlchemy UnitOfWork + transaction semantics.

## 9. Preserved stop rules

The accepted implementation does not require:

```text
fake legacy anchor/job ids
invented history or event/session identity
lossy string-to-BIGINT conversion
session-based notification idempotency
repository-owned commit
provider/network calls inside repository persistence
legacy runtime imports
UNKNOWN -> OFFLINE
```
