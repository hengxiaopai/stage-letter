# Stage Letter V0.1 — Gate 0A Douyin Live Data Source

Status: **IN PROGRESS**  
Gate 0B: **NOT STARTED**

## 1. Objective

Prove whether Stage Letter can obtain sufficiently trustworthy real-time Douyin live-state facts for ordinary public creators and normalize them into:

- `LIVE`
- `OFFLINE`
- `UNKNOWN`

Gate 0A does not approve a production data source merely because a technical probe works.

## 2. Source classes

| Source class | Purpose | Production status |
|---|---|---|
| `OFFICIAL` | Douyin-authorized capabilities / Live SDK | Preferred production candidate |
| `COMMERCIAL_API_CANDIDATE` | Paid provider with stable API contract | Technical candidate; rights review required |
| `THIRD_PARTY_PUBLIC_API` | Free/public aggregation API | Experimental only |
| `PUBLIC_WEB_PROBE` | Direct public-web observation | Experimental only; not production approved |

## 3. Core invariants

1. Probe failure is never equal to `OFFLINE`.
2. HTTP 4xx/5xx, timeout, risk-control, DNS/network failure and parse ambiguity produce `UNKNOWN` unless the provider returns explicit trustworthy live-state evidence.
3. `OFFLINE` requires explicit offline evidence.
4. `LIVE` requires explicit live evidence such as `live_status=1`, a trustworthy live room result, or equivalent provider evidence.
5. Gate 0A does not create `LiveSession` and does not send notifications.
6. No third-party reverse-engineering/signing source code is copied into Stage Letter.
7. Metadata from an ambiguous provider response must not be emitted as trusted creator/live metadata.
8. Technical usability does not establish production authorization.
9. TikHub credentials remain server-side/local-process only and never enter the WeChat mini-program bundle.

## 4. Persistent product target

```text
DY-TARGET-001
Label: X.四五六
Known webcast candidate: 975645387460
Known room URL: https://live.douyin.com/975645387460
```

The new primary Stage Letter identity key is no longer `webcast_id`. Gate 0A now resolves and retains Douyin `uid` / `sec_uid` as `PlatformAccount` identifiers.

## 5. Gate 0A.1 — Plain public-room HTML

Evidence:

```text
GitHub Actions run: 31779812353
HTTP status: 200
Response bytes: 999963
Status: UNKNOWN
Error: AMBIGUOUS_PAGE
```

Decision:

```text
PLAIN_PUBLIC_ROOM_HTML = INSUFFICIENT
```

A plain anonymous room-page request is not a reliable Stage Letter live-state source.

## 6. Rejected public aggregators

### FFAPI

```text
GitHub Actions run: 31780103280
Targets: 8 real IDs + 1 invalid control
LIVE: 0
UNKNOWN: 9
Failure: Connection refused
Decision: REJECTED
```

### iLingku

```text
GitHub Actions run: 31780201967
Targets: 8 real IDs + 1 invalid control
LIVE: 0
UNKNOWN: 9
Failure: DNS resolution failed
Decision: REJECTED
```

The anonymous/free aggregator branch is stopped.

## 7. TikHub commercial technical candidate

### 7.1 Authentication / billing path

TikHub authentication is proven working from the local Gate 0A proxy.

Observed product-target call:

```text
webcast_id: 975645387460
HTTP: 200
provider_code: 200
provider_message: 请求成功，本次请求将被计费。
status: UNKNOWN
error: PROVIDER_AMBIGUOUS
```

Interpretation: authentication and billing work, but `fetch_user_live_videos?webcast_id=...` did not provide decisive live-state evidence for this target at that observation time. `data=null` is not treated as OFFLINE.

The account has subsequently been funded, so `PAYMENT_REQUIRED` is no longer the current blocker.

### 7.2 Live-search branch — diagnostic only

Both V3 and V1 live-search calls returned HTTP 400 after account funding despite documented request shapes.

Observed examples:

```text
fetch_live_search_v3 -> HTTP 400
fetch_live_search_v1 -> HTTP 400
```

Decision:

```text
LIVE_SEARCH = DIAGNOSTIC_ONLY
```

Do not use keyword live-search as Stage Letter's primary monitoring architecture.

## 8. Gate 0A.2 primary path — Creator -> UID -> live_status

TikHub's current documented APIs provide a path that matches Stage Letter's real product model better than live-search:

```text
Creator nickname / Douyin ID
        ↓
POST /api/v1/douyin/search/fetch_user_search_v2
        ↓
uid
sec_uid
nickname
unique_id
follower_count
live_status
        ↓
GET /api/v1/douyin/web/fetch_user_live_info_by_uid?uid=<uid>
        ↓
room_id
live_status
        ↓
LIVE / OFFLINE / UNKNOWN
```

`fetch_user_search_v2` is used only for creator resolution / adding an 爱播. The long-running monitor should persist the resolved `uid` and call the UID live-info endpoint directly.

### 8.1 New implementation

Files:

```text
experiments/gate0a/tikhub_creator_status_probe.py
experiments/gate0a/local_proxy.py
```

Local proxy version:

```text
StageLetterGate0A/0.4
```

New routes:

```text
GET /api/gate0a/douyin/creator-search?keyword=X.四五六
GET /api/gate0a/douyin/creator-status?keyword=X.四五六
GET /api/gate0a/douyin/uid-live?uid=<uid>
```

Legacy/diagnostic routes remain available:

```text
GET /api/gate0a/douyin/live-search?keyword=...
GET /api/gate0a/douyin/live?webcast_id=...
```

### 8.2 Classification rules

Primary confidence:

```text
fetch_user_live_info_by_uid explicit live_status
→ LIVE/OFFLINE
→ confidence 0.95
```

Fallback confidence:

```text
fetch_user_search_v2 explicit live_status
+ UID endpoint inconclusive
→ LIVE/OFFLINE
→ confidence 0.80
```

No explicit status:

```text
→ UNKNOWN
```

No network/provider failure may be converted into OFFLINE.

### 8.3 CI evidence

Upgrade commit:

```text
fe4a29d9fa2e5003c77c537fcffe7d1a25b470ed
```

GitHub Actions:

```text
Gate 0A Local Preview Safety run: 31951720168
Result: PASS
- Python syntax: PASS
- missing-secret fail-closed: PASS
- mini-program contains no TikHub credential access: PASS

Gate 0A Douyin Smoke run: 31951720189
Result: PASS
```

## 9. Gate 0A.2 remaining acceptance

Required next evidence:

- [ ] `X.四五六` resolves to a concrete Douyin `uid` / `sec_uid` without ambiguous selection.
- [ ] The selected UID returns explicit `live_status` from either search V2 or UID live-info.
- [ ] At least one real OFFLINE creator is correctly returned as `OFFLINE`.
- [ ] At least five creators independently known to be LIVE return `LIVE` without false OFFLINE.
- [ ] For LIVE creators, `room_id` coverage is recorded.
- [ ] The same persisted UID can be queried repeatedly without re-searching the nickname.

Only after these pass may Stage Letter start the real transition run.

## 10. Gate 0A.3 — Real lifecycle acceptance

Required real lifecycle:

```text
OFFLINE -> LIVE -> OFFLINE
```

- [ ] At least one real creator lifecycle captured.
- [ ] Transient `UNKNOWN` does not fabricate state transitions.
- [ ] Observation timestamps retained.
- [ ] No duplicate lifecycle inferred from retries.

State/session confirmation itself belongs to Gate 0B.

## 11. Gate 0A.4 — Stability evidence

- [ ] Repeated observations collected.
- [ ] HTTP success rate measured.
- [ ] UNKNOWN rate measured.
- [ ] P50/P95 latency measured.
- [ ] 400/401/402/403/422/429/5xx counts measured.
- [ ] Response-structure changes documented.
- [ ] Mainland `.dev` vs global `.io` base domain compared if needed.

## 12. Production authorization blocker

TikHub remains:

```text
COMMERCIAL_API_CANDIDATE
production_approved = false
```

Even if Gate 0A technical evidence passes, Stage Letter still needs an authorization basis suitable for production use. Preferred paths remain:

1. Douyin official Live SDK / official cooperation.
2. A contracted commercial provider with explicit rights suitable for Stage Letter's intended use.

## 13. Current result

```text
Technical feasibility: PROMISING
Plain public HTML: INSUFFICIENT
FFAPI: REJECTED
iLingku: REJECTED
Free aggregator branch: STOPPED
TikHub authentication: PASS
TikHub billing: PASS
TikHub webcast direct state: INCONCLUSIVE
TikHub live-search: DIAGNOSTIC / HTTP 400
TikHub creator UID path: IMPLEMENTED / READY FOR REAL TEST
Production authorization: UNRESOLVED
Gate 0A: IN PROGRESS
Gate 0B: NOT STARTED
```

## 14. Immediate next action

Run the new primary path locally against the product target:

```text
/api/gate0a/douyin/creator-status?keyword=X.四五六
```

If creator resolution is exact and a decisive status is returned, retain the resulting `uid` and immediately re-test with:

```text
/api/gate0a/douyin/uid-live?uid=<resolved_uid>
```

This is the first Stage Letter Gate 0A path that directly matches the intended production monitoring model.
