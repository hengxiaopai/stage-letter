# Gate 1.2-4 — Application Services

Status: **PASS / CLOSED**

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

## 2. Accepted service scope

Landed package:

```text
stage_letter/application/errors.py
stage_letter/application/services/
  __init__.py
  creator.py
  follow.py
  live.py
```

Accepted use-cases:

```text
CreatorApplicationService
  save already-resolved Creator/Profile/PlatformAccount
  validate cross-entity creator identity
  one UnitOfWork + explicit commit

FollowApplicationService
  follow / unfollow account
  derive creator identity from persisted PlatformAccount
  manage NotificationPreference separately

LiveObservationApplicationService
  persist normalized LiveObservation unchanged
  preserve UNKNOWN as UNKNOWN
  no state transition/session/event/provider interpretation
```

## 3. Explicit non-scope

Gate 1.2-4 intentionally does not implement:

```text
platform adapter/provider calls               Gate 1.3
monitoring scheduler / source collection      Gate 1.4
canonical state transition execution          Gate 1.4 / 1.5
session/event lifecycle runtime                Gate 1.5
notification eligibility / queue / provider   Gate 1.6
HTTP API contract                             Gate 1.7
miniapp integration                           Gate 1.8
```

Gate 0B/0C/0D semantics remain authoritative.

## 4. Accepted evidence

User-local acceptance:

```text
Dedicated application-service contracts: 10 tests PASS
Full Gate 1 suite:                       98 tests PASS
```

The contract suite proves:

```text
creator bundle writes + explicit commit
creator/profile/account identity mismatch rejection
follow derives creator identity from persisted account
missing account fails before write/commit
Follow != NotificationPreference
unfollow does not silently rewrite preference
LiveObservation is persisted unchanged, including UNKNOWN
missing account prevents observation write
application services import no infrastructure/framework/legacy runtime
live observation service owns no LiveSession/LiveEvent transition logic
```

## 5. Acceptance result

```text
A. Gate 1.2-3 PASS                                        PASS
B. service dependency boundary frozen                     PASS
C. CreatorApplicationService contracts                    PASS
D. FollowApplicationService contracts                     PASS
E. LiveObservationApplicationService contracts            PASS
F. Follow != NotificationPreference preserved             PASS
G. service layer does not own state-engine semantics      PASS
H. service layer has no infrastructure/framework imports  PASS
I. dedicated service contract tests                       PASS / 10
J. full Gate 1 suite                                      PASS / 98
```

Gate 1.2-4: **PASS / CLOSED**.

## 6. Preserved rules

```text
application must not import stage_letter.infrastructure
application must not import api/workers/core/platform_adapters/experiments
no generated fake persistence ids
no provider/network calls inside UnitOfWork
Follow and NotificationPreference stay separate
raw observation is not canonical composed state
UNKNOWN is never coerced to OFFLINE
no premature LiveSession/LiveEvent transition logic
no implicit transaction commit
```
