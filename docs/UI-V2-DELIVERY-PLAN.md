# StageLetter UI V2 Delivery Plan

## Outcome

StageLetter V1 is not only an “is the streamer live?” tool. The next release turns reliable live observations into a user-owned streamer record while keeping notification delivery trustworthy.

The delivery order is frozen as:

```text
D1 Viewer Context / Reminder Preference
  -> D4 Formal Session Metadata Parity
  -> D2 Sessions / Calendar / Stats
  -> D3 Personal Streamer Profile
  -> Backend Contract Freeze
  -> Figma UI Master / State Gallery
  -> Mini Program implementation
  -> DevTools + real-device acceptance
```

Do not start the next Gate until the current Gate has code, tests, evidence, and explicit approval.

## Current work

### D1 — Viewer Context and Reminder Preference

Status: implementation complete; committed as `bf589ec8`.

Acceptance:

- Detail responses expose the current viewer's Formal Follow and NotificationPreference.
- The Mini Program has no hard-coded reminder-on state.
- Reminder GET/PATCH verifies ownership.
- PATCH updates Formal truth and Legacy compatibility data in one transaction.
- Save failure restores the previous switch value.
- Tests include real local PostgreSQL evidence.
- No visual redesign is included in this Gate.

### D4 — Formal Consumer Parity

Status: implementation complete; migration and PostgreSQL acceptance passed.

- Persist live title, cover, viewer count, provider room identity, and trustworthy source metadata in Formal LiveSession.
- Keep Legacy and Formal response shapes equivalent.
- A changed room ID for the same UID creates a new session.
- Provider enrichment must not decide LIVE/OFFLINE truth.

Evidence and frozen field semantics: `docs/gate1/UI_V2_D4_FORMAL_SESSION_PARITY.md`.

### D2 — Sessions, Calendar, and Stats

- Add cursor-paginated session history.
- Add monthly calendar aggregation with monitoring coverage.
- Add factual statistics: days, sessions, total/average/min/max duration, start-time and weekday distributions.
- Precision-sensitive time analysis uses trusted platform timestamps only.
- Missing observations must not be presented as confirmed “did not stream”.

### D3 — Personal Streamer Profile

- User remark, alias, group, personal tags, and reference schedule.
- Separate user-authored facts from system-derived labels.
- Reference schedule and analytics rules require minimum sample and confidence definitions.

## Design freeze

Figma is the final UI Master, not a speculative scratchpad. Broad UI work resumes after the core backend contract is frozen.

The Alpha/V1 Master must cover Home (live/empty), All Live, Discovery/search/paste-link, Activity, Streamer Detail (overview, history list/calendar, stats, analysis, profile), My Subscriptions, Notification History, Profile, Settings, and State Gallery.

State Gallery must include `LIVE`, `OFFLINE`, `CHECKING`, `UNKNOWN`, `ERROR`, loading, empty, no subscription, no activity, notification denied, platform degraded, streamer unavailable, partial coverage, and no historical data.

Gifts, gift rankings, barrage semantics, commerce, and a full community remain `FUTURE` and do not enter the V1 Master.

## Collaboration model

| Responsibility | Owner | Deliverable |
|---|---|---|
| Product scope, field semantics, Gate decision | Product/ChatGPT review | Frozen contract and PASS/FAIL decision |
| Local implementation, migrations, API, tests, Mini Program | Codex | Small reviewable changes plus evidence |
| UI Master and State Gallery | Product + Figma | Frozen screens, components, states, interaction notes |
| Platform capability evidence | TikHub REST fixtures + adapter probes | Redacted raw samples and capability matrix |
| Runtime acceptance | WeChat DevTools + real device | Screenshots, logs, notification and navigation evidence |
| Change review/history | GitHub | Branch, commit, PR/diff, CI status |

TikHub MCP may be used for development research and endpoint discovery. Production Workers continue to call the approved REST adapter and must not depend on MCP.

## Gate evidence template

Each Gate handoff includes:

1. Scope and explicit non-goals.
2. Data/API contract and null/error policy.
3. Migration status on local Docker PostgreSQL.
4. Focused tests and full regression result.
5. Mini Program/real-device evidence when UI changes exist.
6. Known pre-existing failures separated from regressions.
7. Commit/PR link after review authorization.
