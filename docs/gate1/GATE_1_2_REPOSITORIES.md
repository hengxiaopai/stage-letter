# Gate 1.2-2 — SQLAlchemy Repository Implementations

Status: **CURRENT / IDENTITY CONTRACT LANDED / WRITE-BRIDGE DESIGN REQUIRED**

Entry authority: Gate 1.2-1 PASS.

## 1. Purpose

Gate 1.2-2 implements the four persistence ports frozen in Gate 1.1:

```text
CreatorRepository
FollowRepository
LiveRepository
NotificationRepository
```

Target package:

```text
stage_letter/infrastructure/db/repositories/
```

Repositories translate persistence rows to/from formal domain objects. They do
not own live-state transitions, notification eligibility, provider behavior, or
transaction commits.

## 2. Identity contract

Formal domain/application identifiers are strings, while the PostgreSQL schema
retains BIGINT primary keys for users, creators, platform accounts, and live
sessions.

Gate 1.2 therefore makes the translation explicit at the repository boundary:

```text
User.user_id                 <-> users.id BIGINT
Creator.creator_id           <-> creators.id BIGINT
PlatformAccount.account_id   <-> platform_accounts.id BIGINT
LiveSession.session_id       <-> live_sessions.id BIGINT
```

The persisted numeric identity is exposed as its canonical positive ASCII
decimal string. No hashing, truncation, fallback generation, leading-zero alias,
or lossy coercion is allowed.

Implemented helper:

```text
stage_letter/infrastructure/db/repositories/identity.py
```

Formal evidence identities remain native strings and are persisted verbatim:

```text
LiveObservation.observation_id -> live_observations.observation_id
LiveEvent.event_id              -> live_events.event_id
DeliveryKey.live_event_id       -> LiveEvent.event_id semantic identity
```

`DeliveryKey.live_event_id` is therefore not the numeric foreign-key value in
`notification_deliveries.live_event_id`; NotificationRepository must resolve the
formal event id to the event row before writing/querying a delivery.

## 3. Legacy bridge constraints discovered before implementation

Gate 1.1 deliberately retained legacy columns during EXPAND/hardening. Current
formal ORM models still map several old NOT NULL bridge columns:

```text
platform_accounts.anchor_id
live_sessions.anchor_id
live_sessions.platform
live_events.anchor_id
notification_deliveries.notification_job_id
```

These columns create an important write-path constraint:

- A new formal PlatformAccount cannot safely invent a legacy `anchor_id` row.
- A new formal NotificationDelivery cannot safely invent a legacy
  `notification_job_id` merely to satisfy the old schema.
- Session/event legacy fields may be derived only when the source account already
  carries explicit persisted legacy facts; they must never be fabricated.

Therefore Gate 1.2-2 MUST NOT implement writes using sentinel ids (`0`, `-1`),
generated fake legacy rows, copied unrelated rows, or guessed historical facts.

## 4. Required bridge resolution

Before the four repository implementations can be accepted, the repository
write path needs one explicit forward-compatible strategy.

Preferred direction for Gate 1.2 is a forward-only compatibility relaxation:
legacy bridge columns that are no longer canonical may become nullable for new
formal writes, while existing legacy rows and tables remain untouched. Canonical
foreign keys (`creator_id`, `platform_account_id`, `live_event_id`) remain the
formal truth.

Any such migration must be additive/non-destructive and re-run clean + legacy
migration validation. No historical migration is edited.

Until that bridge is proven, Gate 1.2-2 remains CURRENT rather than pretending
that repository writes are production-ready.

## 5. Repository behavior freeze

All four implementations must obey:

```text
read/write only through the supplied SQLAlchemy AsyncSession
no session.commit() inside repository methods
no provider/network calls
no state-machine decisions
no notification eligibility decisions
no UNKNOWN -> OFFLINE transformation
no imports from api/workers/core/platform_adapters/experiments
DB uniqueness/constraint violations are not silently reclassified as success
```

Expected mapping behavior:

```text
CreatorRepository
  DB creator/profile/account rows <-> Creator/CreatorProfile/PlatformAccount

FollowRepository
  follows/preferences rows <-> Follow/NotificationPreference

LiveRepository
  observations/sessions/events rows <-> LiveObservation/LiveSession/LiveEvent
  get_open_session uses ended_at IS NULL formal truth
  event lookup uses formal event_id

NotificationRepository
  logical key = (user_id, formal live_event_id, channel)
  create_delivery returns False only when that exact logical row already exists
  AMBIGUOUS and all Gate 0D delivery states are preserved verbatim
```

## 6. Current evidence assets

```text
stage_letter/infrastructure/db/repositories/__init__.py
stage_letter/infrastructure/db/repositories/identity.py
tests/gate1/test_repository_identity.py
```

The identity tests prove canonical BIGINT/string round-trip and reject lossy or
ambiguous conversions.

## 7. Acceptance plan

Gate 1.2-2 PASS requires:

```text
A. Gate 1.2-1 remains PASS                                  PASS
B. persistence identity contract frozen                     PASS
C. identity contract tests pass                             PENDING LOCAL EVIDENCE
D. legacy write-bridge strategy implemented safely          PENDING
E. CreatorRepository implements port                        PENDING
F. FollowRepository implements port                         PENDING
G. LiveRepository implements port                           PENDING
H. NotificationRepository implements event-key identity     PENDING
I. repositories never commit independently                  PENDING
J. repository tests against PostgreSQL pass                 PENDING
K. full Gate 1 suite remains green                          PENDING
L. formal boundary AST tests remain green                   PENDING
```

Gate 1.2-2 remains **CURRENT** until all items pass.

## 8. Stop rules

Stop with FAIL/BLOCKED if repository implementation would require:

```text
fake legacy anchor/job ids
invented history or event/session identity
lossy string-to-BIGINT conversion
session-based notification idempotency
repository-owned commit
provider/network call inside repository persistence flow
legacy runtime package import
UNKNOWN -> OFFLINE
```
