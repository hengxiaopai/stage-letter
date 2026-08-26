# UI V2 D2 — Session History, Calendar, and Statistics

## Scope

D2 adds read-only Formal Creator endpoints:

- `GET /api/v1/anchors/{creator_id}/sessions?limit=&cursor=`
- `GET /api/v1/anchors/{creator_id}/calendar?month=YYYY-MM`
- `GET /api/v1/anchors/{creator_id}/stats?from=YYYY-MM-DD&to=YYYY-MM-DD`

`creator_id`, `session_id`, `account_id`, and provider room IDs are string identities in the product contract. The route keeps the existing `anchors` URL for Mini Program navigation compatibility; its identifier is the Formal Creator persistence identity.

## Field truth classes

| Field | Class | Rule |
|---|---|---|
| session/account/platform/title/cover/viewer | NOW | durable session snapshot |
| displayed start | DERIVED | `source_started_at` when present, otherwise probe transition time; it is presentation-only |
| calendar/stats boundary | DERIVED | trusted platform `source_started_at` when `started_at_source=platform`; otherwise immutable `opened_at` |
| `started_at_source` | DERIVED | `platform` or `probe`; UI must not imply probe time is exact |
| ended time | NOW | confirmed transition/probe time, not provider-authored end time |
| duration | DERIVED | `PLATFORM_START_PROBE_END`, `PROBE_START_PROBE_END`, or `UNAVAILABLE`; `duration_is_estimated=true` always, because end evidence is a probe |
| start-hour/weekday distribution | DERIVED | only sessions with trusted platform start timestamps |
| monitoring coverage | DERIVED | distinct observed account-days / eligible account-days |

No observation is never interpreted as `OFFLINE`. Coverage states are `NONE`, `PARTIAL`, or `OBSERVED_DAILY`; even `OBSERVED_DAILY` means day-presence evidence, not continuous monitoring.

## Pagination and performance

History uses a URL-safe opaque cursor containing the immutable complete `(opened_at, session_id)` key. Calendar and stats deliberately use a separate effective boundary timestamp: a trusted platform `source_started_at` when available, otherwise `opened_at`. This prevents a platform-confirmed 23:58 Beijing start observed at 00:02 from being assigned to the wrong month. PostgreSQL indexes support creator-to-account lookup and account session keyset scans. Offset pagination is not part of the contract.

For calendar day and range-level duration aggregates, a homogeneous completed sample reports its shared duration basis. A heterogeneous completed sample reports `MIXED`; an all-open sample reports `UNAVAILABLE`. This does not change the exact per-session basis above.

The acceptance run also found that explicit Formal Creator imports had advanced
table IDs without advancing `creators_id_seq`. A forward-only compatibility
migration aligns the sequence with the current maximum; it does not rewrite any
Creator identity or business row.

## Explicit non-goals

- no inferred end time or fabricated historical observation;
- no UI mock data or broad Mini Program redesign;
- no schedule prediction, gifts, community, or profile annotations (D3/FUTURE).

## Acceptance evidence

- Alembic head: `c82e7a4d1f30` on the existing local Docker PostgreSQL 16 database.
- Existing database rows were preserved; D2 repository probes use isolated rows and roll back.
- D2.1 temporal-boundary probe: a trusted `2026-07-31 23:58 Asia/Shanghai` start observed at `2026-08-01 00:02 Asia/Shanghai` is returned by July only, excluded from August, and has matching July/August statistics assertions.
- D2.1 focused unit and persistence regression: PASS (`27 passed`); D2 PostgreSQL probe: PASS; Gate 5.4 PostgreSQL regression probe: PASS.
- D4 PostgreSQL regression probe: PASS.
- D2 PostgreSQL history/range/coverage probe: PASS.
- Focused D2 and persistence regression: `52 passed`.
- Full repository: `819 passed`, `181 subtests passed`, `2 failed`, `10 errors`.
  The remaining results pre-date D2: ten legacy tests request a removed `db`
  fixture, one Gate 4 test has an outdated Mini Program page list, and one old
  session fill test omits the now-required Formal `creator_id`.
