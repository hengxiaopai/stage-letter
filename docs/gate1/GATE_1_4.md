# Gate 1.4 — Monitoring Scheduler + Observation Pipeline

Status: **PASS / CLOSED**

Entry authority: Gate 1.3 PASS / CLOSED.
Exit: Gate 1.5 CURRENT.

## 1. Goal

Gate 1.4 connects the accepted four-platform adapter framework to durable monitoring without allowing scheduler mechanics, provider failures, or weak metadata to rewrite canonical live truth.

```text
explicitly enabled PlatformAccount
  -> deterministic target discovery
  -> scheduler logical probe
  -> formal AdapterRegistry
  -> LivePlatformAdapter.get_live_snapshot()
  -> normalized LiveSnapshot
  -> durable LiveObservation
  -> Gate 1.5 state/session/event persistence
```

Gate 1.4 owns target discovery, scheduling/probe orchestration, worker composition, and observation ingestion only. It does not create/close LiveSession, emit LiveEvent, or decide notification eligibility.

## 2. Closed slices

```text
Gate 1.4-1  Monitoring Target Discovery + Paging Contract        PASS / CLOSED
Gate 1.4-2  Probe Request + LiveSnapshot -> LiveObservation      PASS / CLOSED
Gate 1.4-3  Scheduler Cadence / Concurrency / Backoff            PASS / CLOSED
Gate 1.4-4  Worker Composition + Four-platform Runtime Wiring    PASS / CLOSED
Gate 1.4-5  Observation Durability / Restart Acceptance          PASS / CLOSED
```

Accepted deterministic evidence:

```text
1.4-1   8 / 8 dedicated + 243 / 243 complete Gate 1 PASS
1.4-2  10 / 10 dedicated + 253 / 253 complete Gate 1 PASS
1.4-3  10 / 10 dedicated + 263 / 263 complete Gate 1 PASS
1.4-4  10 / 10 dedicated + 273 / 273 complete Gate 1 PASS
1.4-5  10 / 10 dedicated + 283 / 283 complete Gate 1 PASS
```

## 3. Durable logical probe identity

The historical observation identity remains valid for legacy/provider evidence:

```text
(platform_account_id, source, observation_id)
```

Formal scheduler-generated observations additionally use the namespace:

```text
monitor:<logical-id>
```

and migration `d14e7c9a5b30_gate14_monitor_probe_identity.py` adds:

```text
uq_g14_monitor_probe_identity
  UNIQUE (platform_account_id, observation_id)
  WHERE observation_id LIKE 'monitor:%'
```

The migration refuses pre-existing duplicate `monitor:*` evidence rather than deleting, merging, or rewriting it. Legacy/non-monitor rows retain the historical source-scoped identity.

`LiveRepository.append_observation()` reports whether the transaction inserted the durable row. A losing concurrent writer re-reads the durable winner and returns it as reused existing work. This closes duplicate durable observation rows for one formal scheduler probe.

## 4. Accepted PostgreSQL durability evidence

User-local PostgreSQL evidence:

```text
migration_head                        d14e7c9a5b30
independent_session_insert_results    one True + one False
row_count_after_race                  1
row_count_after_engine_restart        1
durable_winner_source                 gate14.race.a
durable_winner_status                 LIVE
provider_exactly_once_claimed         false
production_approved                   false
```

This proves one durable observation row survives independent-session contention and a database-engine restart boundary. It does **not** prove exactly-once provider execution; two OS processes may both perform provider I/O before one loses the database insert race.

## 5. Frozen Gate 1.4 boundaries

```text
UNKNOWN remains UNKNOWN
provider I/O stays outside UnitOfWork
scheduler retry reuses one logical probe id
worker construction performs no DB/provider I/O
StreamGet remains lazy
four-platform registry is bilibili/douyin/douyu/huya only
Gate 1.4 does not create LiveSession or LiveEvent
Gate 1.4 does not decide notification eligibility
formal runtime does not import platform_adapters or experiments
```

## 6. Exit

```text
Gate 1.4-5  PASS / CLOSED
Gate 1.4    PASS / CLOSED
Gate 1.5    CURRENT
```

Gate 1.5 owns canonical state reduction plus atomic LiveSession/LiveEvent persistence from already-durable LiveObservation evidence.

## 7. Inherited caveat

Gate 0A remains **DEGRADED** for the deferred same-creator OFFLINE -> LIVE -> OFFLINE lifecycle evidence gap. Gate 1.4 closes without fabricating that missing historical lifecycle evidence.
