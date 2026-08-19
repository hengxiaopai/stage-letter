# Gate 1.2-4 — Application Services

Status: **CURRENT / SERVICE BOUNDARY + INITIAL USE-CASES LANDED / LOCAL EVIDENCE PENDING**

Entry authority: Gate 1.2-3 PASS.

## 1. Purpose

Gate 1.2-4 introduces the first formal application-service layer above the
accepted repository and UnitOfWork boundaries.

The application layer owns use-case orchestration and explicit transaction
commit. It remains independent of SQLAlchemy, FastAPI, Redis, provider SDKs,
workers, and all legacy runtime packages.

Canonical direction:

```text
API / Worker composition root
  -> application service
      -> UnitOfWork port
          -> repository ports
              -> domain
```

Infrastructure implements ports but is never imported by application services.

## 2. Initial service scope

Landed package:

```text
stage_letter/application/services/
  __init__.py
  creator.py
  follow.py
  live.py

stage_letter/application/errors.py
```

Initial use-cases are deliberately narrow.

### CreatorApplicationService

`save_bundle()` persists an already-resolved formal creator aggregate:

```text
Creator
+ optional CreatorProfile
+ optional PlatformAccount
-> one UnitOfWork
-> explicit commit
```

Cross-entity creator identity must match before the UnitOfWork is entered.
The service does not generate persistence ids and does not call adapters.

### FollowApplicationService

`follow_account()` resolves the formal PlatformAccount, derives the Creator
identity from that persisted account, saves Follow, and commits.

`set_notification_preference()` remains a separate use-case. Follow and
NotificationPreference are not collapsed back into one object.

`unfollow_account()` removes only the Follow relation. It does not implicitly
rewrite NotificationPreference; later notification eligibility still requires
the independent follow + preference truths.

### LiveObservationApplicationService

`record()` persists one already-normalized LiveObservation through the formal
LiveRepository and commits.

It does **not** decide transitions, create/close LiveSession, create LiveEvent,
convert UNKNOWN to OFFLINE, compose provider sources, or enqueue notifications.
Those responsibilities remain in their later gates.

## 3. Explicit non-scope

Gate 1.2-4 does not implement:

```text
platform adapter/provider calls               Gate 1.3
monitoring scheduler / source collection      Gate 1.4
canonical state-engine transition execution   Gate 1.4 / 1.5
session/event lifecycle migration              Gate 1.5
notification eligibility / queue / provider   Gate 1.6
HTTP API transport contract                    Gate 1.7
miniapp integration                            Gate 1.8
```

Gate 0B/0C/0D semantics remain authoritative and are not redefined here.

## 4. Error boundary

Application-service failures use formal application errors:

```text
ApplicationServiceError
ApplicationInvariantError
ApplicationNotFoundError
```

Repositories continue to own persistence mapping errors. API/workers may later
translate application errors at their composition boundary; application code
must not import HTTP/framework exception types.

## 5. Transaction rules

Every write use-case must follow:

```text
async with UnitOfWork
  -> read/validate through ports
  -> perform repository writes
  -> explicit uow.commit()
```

No service may call a concrete SQLAlchemy implementation directly. No provider
or network call belongs inside this DB transaction.

## 6. Contract tests

Landed:

```text
tests/gate1/test_application_services.py
```

The contracts verify:

```text
creator bundle writes + explicit commit
creator/profile/account cross-identity validation
follow derives creator identity from persisted PlatformAccount
missing account fails before write/commit
Follow and NotificationPreference remain separate
unfollow does not silently rewrite preference
LiveObservation is persisted unchanged, including UNKNOWN
missing account prevents observation write
application services import no infrastructure/framework/legacy runtime
live observation service owns no LiveSession/LiveEvent transition logic
```

## 7. Acceptance

Gate 1.2-4 PASS requires:

```text
A. Gate 1.2-3 PASS                                        PASS
B. service dependency boundary frozen                     PASS / doc landed
C. CreatorApplicationService contracts                    CODE + TESTS LANDED
D. FollowApplicationService contracts                     CODE + TESTS LANDED
E. LiveObservationApplicationService contracts            CODE + TESTS LANDED
F. Follow != NotificationPreference preserved             CONTRACT LANDED
G. service layer does not own state-engine semantics      CONTRACT LANDED
H. service layer has no infrastructure/framework imports  CONTRACT LANDED
I. dedicated service contract tests pass                  PENDING LOCAL EVIDENCE
J. full Gate 1 suite remains green                        PENDING LOCAL EVIDENCE
```

Gate 1.2-4 remains **CURRENT** until I-J pass.

## 8. Stop rules

Stop with FAIL/BLOCKED if implementation requires:

```text
application importing stage_letter.infrastructure
application importing api/workers/core/platform_adapters/experiments
service generating fake persistence ids
service making provider/network calls inside UnitOfWork
Follow and NotificationPreference being merged
raw observation being treated as canonical composed status
UNKNOWN -> OFFLINE coercion
premature LiveSession/LiveEvent transition logic in Gate 1.2-4
implicit transaction commit
```
