# StageLetter Engineering Rules

These rules are frozen product and engineering constraints for every change in this repository.

1. `UNKNOWN` and `ERROR` must never be converted automatically to `OFFLINE`.
2. For Douyin, `fetch_user_live_info_by_uid` is the truth probe.
3. `room_id_v2` enriches a confirmed live session; it is not evidence for `LIVE` or `OFFLINE` by itself.
4. A successful truth-probe response with `user_live=[]` is provider `OFFLINE` evidence and must still pass the StageLetter state-machine confirmation rules.
5. The same platform UID with a changed `room_id` starts a new `LiveSession`.
6. `owner.modify_time` must not be mapped to `started_at`.
7. Every platform identifier is a string, including `uid`, `room_id`, `stream_id`, `webcast_id`, and `sec_uid`.
8. When no trusted platform start or end time exists, use probe time only with an explicit source and confidence marker.
9. Formal product implementations must not use UI mock data.
10. Normal users must not see raw TikHub/provider errors.
11. Legacy and Formal read paths must preserve Consumer Contract parity during migration.
12. Every Gate follows: code -> migration (when needed) -> tests -> evidence -> stop. Do not enter the next Gate without explicit approval.
13. Product/API fields must be classified as `NOW`, `DERIVED`, `OPTIONAL`, or `FUTURE`; UI may only present `NOW` and trustworthy `DERIVED` values as facts.
14. D1-D4 database acceptance runs against the local Docker PostgreSQL instance. SQLite or mocks may supplement tests but cannot be the only PASS evidence.

Current UI-V2.2 delivery order is `D1 -> D4 -> D2 -> D3`. Figma remains the UI Master, but broad UI implementation waits for backend contract freeze.
