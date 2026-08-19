# Gate 1.2-2 — SQLAlchemy Repository Implementations

Status: **CURRENT / POSTGRESQL REPOSITORY PROBE PASS / STATIC ACCEPTANCE PENDING**

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

## 2. Identity contract — PASS

Formal domain/application identifiers are strings, while the PostgreSQL schema
retains BIGINT primary keys for users, creators, platform accounts, and live
sessions.

Gate 1.2 makes the translation explicit at the repository boundary:

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

Accepted local evidence:

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

`DeliveryKey.live_event_id` is therefore not the numeric foreign-key value in
`notification_deliveries.live_event_id`; NotificationRepository resolves the
formal event id to the event row before writing/querying a delivery.

## 3. Source-scoped observation identity correction

Repository implementation exposed one ambiguity in the original Gate 1.1 port:
`LiveObservation` persistence identity is source-scoped in PostgreSQL, but the
old `has_observation(observation_id)` signature was not.

The formal port is corrected to:

```text
has_observation(account_id, source, observation_id)
```

This aligns the repository API with the already accepted database uniqueness:

```text
(platform_account_id, source, observation_id)
```

The correction narrows ambiguity; it does not change Gate 0 live-state
semantics.

## 4. Legacy write bridge — CODE LANDED

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

The migration permits new formal writes to leave obsolete legacy-only facts
unknown instead of fabricating them.

Relaxed legacy requirements include:

```text
platform_accounts.anchor_id
platform_accounts.last_status
platform_accounts.polling_tier
platform_accounts.canonical_url  # optional in formal domain

live_sessions.anchor_id
live_sessions.platform
live_sessions.state
live_sessions.started_at_source

live_events.anchor_id
live_events.confidence
live_events.detected_at

notification_deliveries.notification_job_id
```

Existing rows are not rewritten. Canonical Gate 1 constraints remain intact.

The obsolete legacy uniqueness:

```text
(user_id, live_session_id, channel)
```

is removed because the accepted canonical delivery identity is:

```text
(user_id, live_event_id, channel)
```

The Gate 1.1 event-keyed unique constraint remains the idempotency authority.

## 5. Repository implementations — CODE LANDED

Current implementation files:

```text
stage_letter/infrastructure/db/repositories/common.py
stage_letter/infrastructure/db/repositories/creator.py
stage_letter/infrastructure/db/repositories/follow.py
stage_letter/infrastructure/db/repositories/live.py
stage_letter/infrastructure/db/repositories/notification.py
```

Implemented behavior:

```text
SQLAlchemyCreatorRepository
  creator/profile/account read + save
  preserves existing legacy bridge evidence
  new formal account may leave legacy anchor/status/tier unknown

SQLAlchemyFollowRepository
  Follow and NotificationPreference remain separate
  read/save/delete through supplied AsyncSession

SQLAlchemyLiveRepository
  source-scoped durable observation identity
  observation append is DB-idempotent
  open-session lookup uses ended_at IS NULL
  session/event writes preserve formal origin/cause
  missing legacy origin/cause is never invented

SQLAlchemyNotificationRepository
  resolves formal LiveEvent.event_id to persisted event row
  logical identity = user/event/channel
  create_delivery is race-safe via PostgreSQL ON CONFLICT
  new delivery does not fabricate notification_job_id
```

## 6. Repository behavior freeze

All four implementations obey:

```text
read/write only through the supplied SQLAlchemy AsyncSession
no session.commit() inside repository methods
no provider/network calls
no state-machine decisions
no notification eligibility decisions
no UNKNOWN -> OFFLINE transformation
no imports from api/workers/core/platform_adapters/experiments
DB uniqueness/constraint violations are not silently reclassified as truth
```

If a persisted legacy row lacks a fact required by the formal domain (for
example a provable session origin), the repository raises a mapping error rather
than inventing a value.

## 7. PostgreSQL acceptance probe — PASS

Probe:

```text
scripts/gate12_repository_probe.py
```

It creates only the isolated temporary database:

```text
stageletter_gate12_repo
```

Accepted user-local evidence:

```text
[gate12] database created
[gate12] seeded at Gate 1.1 head -> b63e4f9a1c20
[gate12] bridge migration PASS -> c91e8d2f4a10
PASS: Gate 1.2-2 SQLAlchemy repositories + legacy write bridge
[cleanup] dropped stageletter_gate12_repo
```

The probe proved:

```text
accepted Gate 1.1 schema can progress to c91e8d2f4a10
representative legacy bridge facts survive unchanged
new formal writes need no fake anchor/job/status/confidence/provenance facts
all four formal repositories can write and read domain objects
source-scoped observation idempotency works in PostgreSQL
event-keyed logical delivery idempotency works in PostgreSQL
temporary probe database is cleaned up
```

An earlier run was blocked before repository execution by direct-script Python
module-path bootstrap (`stage_letter` was not importable when `scripts/` became
`sys.path[0]`). The probe now inserts the repository root before formal imports.
That was a harness startup defect, not a repository or migration semantic
failure; the corrected probe subsequently completed PASS.

The historical Gate 1.1 DB probe remains pinned to `b63e4f9a1c20` so later Gate 1
migrations cannot invalidate reproducibility of accepted Gate 1.1 evidence.

## 8. Current evidence assets

```text
migrations/versions/c91e8d2f4a10_gate12_relax_legacy_write_bridges.py
stage_letter/infrastructure/db/repositories/*
tests/gate1/test_repository_identity.py
tests/gate1/test_repository_implementations.py
scripts/gate12_repository_probe.py
```

## 9. Acceptance plan

Gate 1.2-2 PASS requires:

```text
A. Gate 1.2-1 remains PASS                                  PASS
B. persistence identity contract frozen                     PASS
C. identity contract tests pass                             PASS / 7/7
D. legacy write-bridge strategy implemented safely          PASS / real DB probe
E. CreatorRepository implements port                        PASS / real DB probe
F. FollowRepository implements port                         PASS / real DB probe
G. LiveRepository implements port                           PASS / real DB probe
H. NotificationRepository implements event-key identity     PASS / real DB probe
I. repositories never commit independently                  CONTRACT LANDED
J. repository tests against PostgreSQL pass                 PASS
K. full Gate 1 suite remains green                          PENDING NEW LOCAL EVIDENCE
L. formal boundary AST tests remain green                   PENDING NEW LOCAL EVIDENCE
M. Alembic head == c91e8d2f4a10                            PENDING LOCAL EVIDENCE
N. UTF-8 offline SQL compilation through new head           PENDING LOCAL EVIDENCE
```

Gate 1.2-2 remains **CURRENT** until K-N pass.

## 10. Stop rules

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
