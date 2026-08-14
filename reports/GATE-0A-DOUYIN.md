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
| `OFFICIAL` | Douyin-authorized capabilities / Live SDK | Preferred candidate; broadcaster scope may require authorization/whitelist |
| `COMMERCIAL_API_CANDIDATE` | Paid provider with stable API contract | Technical candidate; Douyin rights must be reviewed separately |
| `THIRD_PARTY_PUBLIC_API` | Free/public aggregation API | Experimental only |
| `PUBLIC_WEB_PROBE` | Direct public-web observation | Experimental only; **not production approved** |

## 3. Core invariants

1. Probe failure is never equal to `OFFLINE`.
2. HTTP `403`, `429`, timeout, risk-control, unavailable content, DNS/network failures, and parse ambiguity produce `UNKNOWN`.
3. `OFFLINE` requires explicit offline evidence.
4. `LIVE` requires decisive live evidence such as trustworthy provider live status or live stream URLs.
5. Gate 0A does not create `LiveSession` and does not send notifications.
6. No third-party reverse-engineering/signing source code is copied into Stage Letter.
7. Metadata from an ambiguous page/provider response must not be emitted as trusted creator/live metadata.
8. A provider being technically usable does not establish authorization to use Douyin data in Stage Letter.

## 4. Persistent test targets

### Product target

- `DY-TARGET-001`
- Label: `X.四五六`
- `web_rid` / webcast candidate: `975645387460`
- URL: `https://live.douyin.com/975645387460`

### Positive-control pool

`experiments/gate0a/provider_targets.json` contains the product target plus multiple real rooms discovered as live controls during Gate 0A research. Their live status must always be independently re-confirmed at execution time; they are not permanently asserted to remain live.

### Negative control

- invalid non-numeric ID
- expected result: `UNKNOWN / INVALID_TARGET`

## 5. Observation contract

All probes normalize to tri-state observations and include source, confidence, latency, provider/error details, and evidence. Sensitive provider tokens are never stored in observation data or committed to Git.

## 6. Gate 0A.1 — Plain public-room HTML

### Acceptance already satisfied

- [x] Repository bootstrap exists.
- [x] Tri-state probe contract exists.
- [x] Invalid target maps to `UNKNOWN` locally.
- [x] Failure classes are modeled separately from `OFFLINE`.
- [x] JSONL evidence output exists.
- [x] `X.四五六` is a persistent product target.
- [x] Evidence directory is ignored by Git.
- [x] Python syntax + smoke execution run successfully in GitHub Actions.
- [x] Ambiguous HTTP 200 page remains `UNKNOWN` and does not leak unrelated bundle metadata.

### Evidence — 2026-08-14

```text
GitHub Actions run: 31779812353
Commit: b3d165a9104f9e4100424307306741f2e9996ea2
Workflow conclusion: success
```

`X.四五六` result:

```text
HTTP status: 200
Latency: 1803 ms
Response bytes: 999963
Status: UNKNOWN
Confidence: 0.1
Error type: AMBIGUOUS_PAGE
Evidence: http_200_but_no_decisive_state_signal
creator_name: null
title: null
room_id: null
source_started_at: null
```

Conclusion:

```text
PLAIN_PUBLIC_ROOM_HTML = INSUFFICIENT
```

A plain anonymous room-page request is not a reliable Stage Letter live-state source.

## 7. Gate 0A.2 — Decisive LIVE source search

### 7.1 FFAPI public API — rejected

Probe files:

- `experiments/gate0a/provider_probe.py`
- `.github/workflows/gate0a-provider-smoke.yml`

Evidence:

```text
GitHub Actions run: 31780103280
Targets: 8 real IDs + 1 invalid control
LIVE: 0
OFFLINE: 0
UNKNOWN: 9
Decisive LIVE found: false
```

All real targets failed with:

```text
NETWORK:[Errno 111] Connection refused
```

Decision:

```text
FFAPI_CN = REJECTED / UNREACHABLE_FROM_TEST_RUNNER
```

Do not retry as an active Gate 0A candidate unless the provider materially changes.

### 7.2 iLingku public API — rejected

Probe files:

- `experiments/gate0a/provider_probe_ilingku.py`
- `.github/workflows/gate0a-ilingku-smoke.yml`

Evidence:

```text
GitHub Actions run: 31780201967
Targets: 8 real IDs + 1 invalid control
LIVE: 0
OFFLINE: 0
UNKNOWN: 9
Decisive LIVE found: false
```

All real targets failed DNS resolution with:

```text
NETWORK:[Errno -2] Name or service not known
```

Decision:

```text
ILINGKU_PUBLIC_API = REJECTED / DNS_UNREACHABLE_FROM_TEST_RUNNER
```

### 7.3 Free/public aggregator branch — stopped

After independent failures of FFAPI and iLingku, Stage Letter stops spending Gate 0A time on anonymous free aggregation APIs. Any future free provider requires a materially stronger reliability signal before testing.

### 7.4 TikHub — active commercial technical candidate

Files:

- `experiments/gate0a/tikhub_probe.py`
- `.github/workflows/gate0a-tikhub-smoke.yml`

Chosen endpoint:

```text
GET https://api.tikhub.io/api/v1/douyin/web/fetch_user_live_videos?webcast_id=<id>
```

Reason: TikHub documents `webcast_id` as the numeric identifier at the end of a Douyin live link and distinguishes it from the per-session `room_id`, matching Stage Letter's existing `web_rid`-style target input.

Preflight evidence:

```text
GitHub Actions run: 31780357301
API host preflight: PASS
Unauthenticated endpoint response: HTTP 401
TIKHUB_API_KEY configured: false
Decisive-live probe: SKIPPED
Blocker: BLOCKED_MISSING_SECRET
```

Interpretation:

- TikHub's API host and selected endpoint are reachable from GitHub Actions.
- The current blocker is authentication, not DNS/network reachability.
- `tikhub_probe.py` reads only the `TIKHUB_API_KEY` environment variable and never prints or commits the token.
- TikHub is an unofficial third-party API; successful technical testing will **not** automatically mark it production-authorized for Stage Letter.

Current TikHub status:

```text
TECHNICAL_PREFLIGHT = PASS
DECISIVE_LIVE_TEST = BLOCKED_MISSING_SECRET
PRODUCTION_AUTHORIZATION = UNRESOLVED
```

### 7.5 Douyin official Live SDK / status capability — preferred production candidate

Keep the official route open in parallel. It is the preferred authorization path, especially for broadcasters that actively authorize Stage Letter or can be included in a cooperation whitelist. The unresolved product question is whether the cooperation model can cover the product's intended ordinary-public-creator use case at sufficient scale.

## 8. Remaining Gate 0A.2 acceptance

- [ ] At least five rooms independently known to be LIVE at execution time return decisive `LIVE` from one candidate source.
- [ ] No known-live control is falsely classified as `OFFLINE`.
- [ ] Creator/title/room metadata coverage is recorded for decisive LIVE observations.
- [ ] At least one real OFFLINE observation is confirmed with explicit evidence.

Only after these pass may Stage Letter begin transition capture.

## 9. Gate 0A.3 — Transition acceptance

Required real lifecycle evidence:

```text
OFFLINE -> LIVE -> OFFLINE
```

- [ ] At least one real creator lifecycle captured.
- [ ] Probe continues through transient `UNKNOWN` without fabricating transitions.
- [ ] Start/end observation timestamps retained.
- [ ] No duplicate lifecycle is inferred from probe retries.

State/session confirmation belongs to Gate 0B; Gate 0A only proves source observations exist.

## 10. Gate 0A.4 — Stability evidence

- [ ] Sufficient repeated observations collected.
- [ ] HTTP success rate measured.
- [ ] `UNKNOWN` rate measured.
- [ ] P50/P95 latency measured.
- [ ] 403 count measured.
- [ ] 429 count measured.
- [ ] timeout/network failure count measured.
- [ ] ambiguous/parse-failure count measured.
- [ ] Response-structure changes documented without committing sensitive/raw data unnecessarily.

## 11. Production authorization blocker

Gate 0A cannot be declared production-ready until at least one data-source path has an authorization basis appropriate for Stage Letter's intended use.

Current candidates:

1. Douyin official Live SDK / official cooperation.
2. A contracted commercial provider, subject to explicit rights/usage review.

TikHub remains `COMMERCIAL_API_CANDIDATE`, not `LICENSED`, until contractual/data-rights review is complete.

## 12. Current result

```text
Technical feasibility: PROMISING
Plain public room HTML: INSUFFICIENT
FFAPI: REJECTED
ILINGKU: REJECTED
Free aggregator branch: STOPPED
TikHub network/endpoint preflight: PASS
TikHub decisive LIVE: BLOCKED_MISSING_SECRET
Official Douyin route: ACTIVE CANDIDATE
Production source authorization: UNRESOLVED
Gate 0A: IN PROGRESS
Gate 0B: NOT STARTED
```

## 13. Next action

Immediate next execution step:

1. Create/obtain a TikHub API key using TikHub's normal account process.
2. Store it only as GitHub repository secret `TIKHUB_API_KEY` for `hengxiaopai/stage-letter`; do not commit or paste the token into issues, logs, source files, or chat.
3. Re-run `Gate 0A TikHub Smoke` against the existing control set.
4. If at least five independently known-live controls return decisive `LIVE`, capture an OFFLINE sample and then start Transition Run.
5. In parallel, continue official Douyin Live SDK/cooperation qualification for the production authorization path.

Until step 3 produces decisive LIVE evidence, Gate 0B remains forbidden.
