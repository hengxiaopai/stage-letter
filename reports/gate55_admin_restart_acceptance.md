# Gate 5.5 — Admin Restart Acceptance

Date: 2026-08-20

`scripts/gate55_admin_restart_probe.py` used a fresh PostgreSQL engine to read
the Admin health, inquiry, and aggregate-metric projections. It disposed that
engine, opened a second fresh engine, and repeated the reads.

Both sides observed four platform rows, eight user rows, eleven subscription
rows, five delivery rows, four platform metric rows, two delivery metric rows,
and one error metric row. The migration head was `f52a9d1c4e81`.

The probe reported `PASS`, `provider_called=false`, `notification_called=false`,
`database_write_performed=false`, and `live_truth_mutated=false`. It does not
claim Gate 0A closure or production approval.
