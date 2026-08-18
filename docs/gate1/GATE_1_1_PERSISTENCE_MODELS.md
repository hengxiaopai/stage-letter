# Gate 1.1-3 — SQLAlchemy Persistence Models

Status: **PASS**

## Purpose

Describe the post-EXPAND SQLAlchemy persistence shape for the ten frozen V0.1 domain entities before writing the Alembic migration.

Target domain tables:

```text
users
creators
creator_profiles
platform_accounts
follows
notification_preferences
live_observations
live_sessions
live_events
notification_deliveries
```

## Rules

1. SQLAlchemy exists only under `stage_letter/infrastructure/db`.
2. Domain and application packages remain infrastructure-free.
3. Existing Alembic history is immutable.
4. Existing legacy columns may remain as explicitly named bridge fields during EXPAND/BACKFILL.
5. Bridge fields are not domain truth and must not leak into the formal domain vocabulary.
6. No historical LiveObservation, source start time, event cause, or provider truth may be invented.
7. Alembic remains schema authority; `metadata.create_all()` is not a migration substitute.

## Formal persistence contracts represented

```text
PlatformAccount -> creator_id owner
Follow -> unique(user_id, platform_account_id)
NotificationPreference -> separate table from Follow
LiveObservation -> first-class durable table
LiveObservation identity -> (platform_account_id, source, observation_id)
LiveSession -> one open session per account via PostgreSQL partial unique index
LiveEvent -> event_id + event_type + cause + occurred_at
NotificationDelivery -> unique(user_id, live_event_id, channel)
NotificationDelivery -> durable runtime fields for IN_FLIGHT/retry state
```

The formal PlatformAccount model intentionally does not expose legacy `last_status` as canonical truth. Runtime source health is also not stored as PlatformAccount live state.

## Transitional legacy bridges

The current pre-Gate-1 schema contains NOT NULL fields that cannot be deleted during EXPAND. The formal infrastructure model therefore names them explicitly as bridge-only fields where required, for example:

```text
legacy_anchor_id
legacy_platform
legacy_state
legacy_detected_at
legacy_confidence
legacy_notification_job_id
```

These fields exist so the forward migration can coexist with historical data. They do not change the frozen domain model and are candidates for a later CONTRACT gate only after reads/writes have moved and verification passes.

## Acceptance tests

`tests/gate1/test_persistence_models.py` checks:

```text
exact ten target domain tables in formal metadata
PlatformAccount creator ownership and absence of legacy canonical last_status
Follow user/account uniqueness
LiveObservation source-scoped stable identity
partial unique open LiveSession index
LiveEvent type/cause separation
NotificationDelivery event-based idempotency
Delivery runtime storage capacity for accepted Gate 0D states
```

## Accepted local evidence

User-local project environment:

```text
Python      3.13.14
SQLAlchemy  2.0.52
Alembic     1.19.1
PASS: Gate 1 DB dependencies available
```

Full Gate 1 suite after SQLAlchemy models landed:

```text
Ran 25 tests in 0.004s
OK
```

Formal metadata load:

```text
creator_profiles
creators
follows
live_events
live_observations
live_sessions
notification_deliveries
notification_preferences
platform_accounts
users
count: 10
PASS: formal persistence metadata loaded
```

Acceptance:

```text
formal metadata exactly ten domain tables                 PASS
persistence contract tests                                PASS
existing domain/application tests remain green            PASS
project DB dependencies available                         PASS
metadata imports successfully                             PASS
```

Gate 1.1-3: **PASS**.

## Next gate

Gate 1.1-4 — Alembic EXPAND Migration is now active.

The migration remains forward-only and may not drop legacy data.
