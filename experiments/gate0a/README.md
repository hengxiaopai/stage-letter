# Stage Letter V0.1 — Gate 0A Douyin Probe

Status: **IN PROGRESS**  
Scope: experimental verification only. This directory is not a production Douyin data source.

## Objective

Verify whether Stage Letter can normalize observable Douyin room facts into the V0.1 tri-state contract:

- `LIVE`
- `OFFLINE`
- `UNKNOWN`

The probe must never convert a network, rate-limit, risk-control, provider failure, or parse failure into `OFFLINE`.

## Non-goals

- No formal product backend.
- No PostgreSQL / Redis / queue.
- No WeChat notification.
- No `LiveSession` creation.
- No production approval of unofficial data sources.
- No TikHub API key in mini-program code, Git history, logs, or committed config.

## Active files

- `douyin_probe.py` — anonymous public-room HTML experiment.
- `tikhub_probe.py` — TikHub commercial technical candidate; reads only `TIKHUB_API_KEY`.
- `local_proxy.py` — local-only Stage Letter proxy for WeChat DevTools.
- `start-local.ps1` — Windows launcher that securely prompts for the TikHub key when it is not already in the environment.
- `.env.example` — key/config template only; real `.env*` files are ignored by Git.
- `provider_targets.json` — current Gate 0A provider target set.
- `wechat-demo/` — minimal WeChat DevTools preview page wired only to the local Stage Letter proxy.
- `data/` — local evidence only; ignored by Git.
- `../../reports/GATE-0A-DOUYIN.md` — Gate evidence and decision log.

## Local TikHub + WeChat DevTools path

Security boundary:

```text
TikHub API key
  ↓ server process environment only
local_proxy.py (127.0.0.1:8765)
  ↓ normalized LIVE/OFFLINE/UNKNOWN only
WeChat DevTools preview page
```

The mini-program never receives the TikHub API key and never calls TikHub directly.

### 1. Pull the current repository

```powershell
git pull
```

### 2. Start the local Gate 0A proxy

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\experiments\gate0a\start-local.ps1
```

If `TIKHUB_API_KEY` is not already set, PowerShell prompts for it with hidden input. The value remains in the current process environment and is not written to disk by the launcher.

Health check:

```text
http://127.0.0.1:8765/health
```

Expected:

```json
{
  "ok": true,
  "service": "stage-letter-gate0a-local-proxy",
  "secret_configured": true,
  "production": false
}
```

Direct product-target check:

```text
http://127.0.0.1:8765/api/gate0a/douyin/live?webcast_id=975645387460&label=X.%E5%9B%9B%E4%BA%94%E5%85%AD
```

### 3. Open the Gate 0A WeChat preview

Use `experiments/gate0a/wechat-demo` as the mini-program source directory, or copy the `pages/index` preview page into the currently open local mini-program project.

For WeChat DevTools local-only testing, enable the development option that skips request-domain/TLS validation so `http://127.0.0.1:8765` is allowed. This localhost route is DevTools-only; a real device cannot use the PC loopback address as the Stage Letter backend.

The page defaults to:

```text
X.四五六
webcast_id = 975645387460
```

It displays:

- `LIVE / OFFLINE / UNKNOWN`
- creator name
- live title
- resolved `room_id`
- stream evidence count (URLs themselves are not exposed to the mini-program)
- confidence
- upstream HTTP status
- latency
- observation time
- error/evidence fields

## TikHub Gate rule

TikHub is currently a **commercial technical candidate**, not a Douyin-official source. A successful `LIVE` response can satisfy Gate 0A's technical decisive-live criterion, but it does not by itself satisfy production authorization.

## Smoke acceptance

1. Every observation emits `LIVE`, `OFFLINE`, or `UNKNOWN` only.
2. Invalid or unreachable targets never become `OFFLINE` merely because probing failed.
3. HTTP `403`, `429`, timeout, risk-control, provider failure, and parse ambiguity map to `UNKNOWN` with an `error_type`.
4. Every record includes `observed_at`, `source_type`, `source_provider`, `confidence`, `latency_ms`, and error metadata.
5. Target `X.四五六` remains a persistent Stage Letter product target.
6. No notification or formal session logic exists in this Gate.
7. TikHub credentials stay server-side only.

Gate 0A remains open until known-live controls produce decisive `LIVE`, a real `OFFLINE -> LIVE -> OFFLINE` lifecycle is captured, and a production-authorized source path is resolved.
