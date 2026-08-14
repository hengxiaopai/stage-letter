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
| `OFFICIAL` | Douyin-authorized capabilities / SDK | Candidate |
| `LICENSED` | Contracted commercial provider | Candidate |
| `PUBLIC_WEB_PROBE` | Experimental public-web observation | **Not production approved** |

Current runnable probe: `PUBLIC_WEB_PROBE / DOUYIN_WEB`.

## 3. Core invariants

1. Probe failure is never equal to `OFFLINE`.
2. HTTP `403`, `429`, timeout, risk-control, unavailable content, and parse ambiguity produce `UNKNOWN`.
3. `OFFLINE` requires explicit offline evidence.
4. `LIVE` requires multiple stream-specific signals in the returned public page.
5. Gate 0A does not create `LiveSession` and does not send notifications.
6. No third-party reverse-engineering/signing source code is copied into Stage Letter.

## 4. Persistent test targets

### Product target

- `DY-TARGET-001`
- Label: `X.四五六`
- `web_rid`: `975645387460`
- URL: `https://live.douyin.com/975645387460`

### Negative control

- `DY-CONTROL-INVALID`
- Invalid non-numeric `web_rid`
- Expected result: `UNKNOWN / INVALID_TARGET`

Current known-live rooms should be appended to a smoke run as ad-hoc controls rather than permanently asserting that they remain live:

```bash
python experiments/gate0a/douyin_probe.py \
  --room "control-a=<current_web_rid>" \
  --room "control-b=<current_web_rid>"
```

## 5. Observation contract

Every JSONL row must include at least:

```json
{
  "platform": "douyin",
  "web_rid": "975645387460",
  "status": "LIVE|OFFLINE|UNKNOWN",
  "creator_name": null,
  "title": null,
  "room_id": null,
  "room_url": "https://live.douyin.com/975645387460",
  "source_started_at": null,
  "observed_at": "...+08:00",
  "source_type": "PUBLIC_WEB_PROBE",
  "source_provider": "DOUYIN_WEB",
  "confidence": 0.0,
  "http_status": 200,
  "latency_ms": 0,
  "error_type": null,
  "evidence": [],
  "response_sha256": null
}
```

## 6. Gate 0A.1 Smoke acceptance

- [x] Repository bootstrap exists.
- [x] Tri-state probe contract exists.
- [x] Invalid target maps to `UNKNOWN` locally.
- [x] Failure classes are modeled separately from `OFFLINE`.
- [x] JSONL evidence output exists.
- [x] `X.四五六` is a persistent product target.
- [x] Evidence directory is ignored by Git.
- [ ] Run the probe against at least five rooms independently known to be LIVE at execution time.
- [ ] All positive controls return `LIVE` or produce an explained `UNKNOWN`; no false `OFFLINE` is accepted.
- [ ] Record returned creator name/title/room metadata coverage.
- [ ] Confirm a real OFFLINE sample with explicit offline evidence.

## 7. Gate 0A.2 Transition acceptance

Required real lifecycle evidence:

```text
OFFLINE -> LIVE -> OFFLINE
```

- [ ] At least one real creator lifecycle captured.
- [ ] Probe continues through transient `UNKNOWN` without fabricating state transitions.
- [ ] Start/end observation timestamps retained.
- [ ] No duplicate lifecycle is inferred from probe retries.

State/session confirmation itself belongs to Gate 0B; Gate 0A only proves the source observations exist.

## 8. Gate 0A.3 Stability evidence

- [ ] Sufficient repeated observations collected.
- [ ] HTTP success rate measured.
- [ ] `UNKNOWN` rate measured.
- [ ] P50/P95 latency measured.
- [ ] 403 count measured.
- [ ] 429 count measured.
- [ ] timeout count measured.
- [ ] ambiguous/parse-failure count measured.
- [ ] Response structure changes documented via hashes/evidence without committing raw local data.

## 9. Production authorization blocker

Even if the experimental probe is technically successful, Gate 0A cannot be declared production-ready until at least one source path has a clear authorization basis for Stage Letter's intended use.

Candidates:

- Douyin official live capability / Live SDK cooperation.
- A licensed commercial data provider whose contract explicitly permits the required real-time live-status use.

Current result:

```text
Technical feasibility: PROMISING
Public-web probe: EXPERIMENTAL
Production source authorization: UNRESOLVED
Gate 0A: IN PROGRESS
Gate 0B: NOT STARTED
```

## 10. Next action

Run `experiments/gate0a/douyin_probe.py` against current live positive controls plus `X.四五六`, then attach the resulting summary statistics to this report before any transition-run work begins.
