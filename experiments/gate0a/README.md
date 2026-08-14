# Stage Letter V0.1 — Gate 0A Douyin Probe

Status: **IN PROGRESS**  
Scope: experimental verification only. This directory is not a production Douyin data source.

## Objective

Verify whether Stage Letter can normalize observable Douyin room facts into the V0.1 tri-state contract:

- `LIVE`
- `OFFLINE`
- `UNKNOWN`

The probe must never convert a network, rate-limit, risk-control, or parse failure into `OFFLINE`.

## Non-goals

- No FastAPI application.
- No PostgreSQL / Redis / queue.
- No WeChat notification.
- No `LiveSession` creation.
- No production approval of `PUBLIC_WEB_PROBE`.
- No copied third-party reverse-engineering/signing implementation.

## Files

- `douyin_probe.py` — minimal independent probe and JSONL writer.
- `targets.json` — persistent target/control cases.
- `data/` — local evidence only; ignored by Git.
- `../../reports/GATE-0A-DOUYIN.md` — Gate evidence and decision log.

## Smoke acceptance

1. Every observation emits `LIVE`, `OFFLINE`, or `UNKNOWN` only.
2. Invalid or unreachable targets never become `OFFLINE` merely because probing failed.
3. HTTP `403`, `429`, timeout, risk-control, and parse ambiguity map to `UNKNOWN` with an `error_type`.
4. Every record includes `observed_at`, `source_type`, `source_provider`, `confidence`, `latency_ms`, and error metadata.
5. Target `X.四五六` remains a persistent Stage Letter product target.
6. No notification or formal session logic exists in this Gate.

## Run

Python 3.11+ is sufficient; no third-party dependency is required.

```bash
python experiments/gate0a/douyin_probe.py
```

Optional:

```bash
python experiments/gate0a/douyin_probe.py --targets experiments/gate0a/targets.json --output experiments/gate0a/data/smoke.jsonl
```

A smoke run is evidence only. Gate 0A remains open until a real `OFFLINE -> LIVE -> OFFLINE` lifecycle is captured and a production-authorized source path is resolved.
