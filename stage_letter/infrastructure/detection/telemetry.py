"""Gate 2.3 operational telemetry persistence.

Uses a separate SQLAlchemy Core MetaData so Gate 1's canonical Base stays frozen.
The existing physical `probe_runs` and `platform_health` tables are operational
surfaces only; they never create or mutate canonical live truth.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    and_,
    case,
    cast,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from stage_letter.detection.contracts import PlatformHealthState
from stage_letter.detection.telemetry import (
    PlatformHealthSnapshot,
    ProbeTelemetryPersistenceResult,
    ProbeTelemetryRecord,
)

SessionFactory = Callable[[], AsyncSession]
TELEMETRY_SCHEMA = "gate2.3"

_metadata = MetaData()
_accounts = Table(
    "platform_accounts",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("platform", String(32), nullable=False),
)
_probe_runs = Table(
    "probe_runs",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("platform_account_id", BigInteger, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("success", Boolean),
    Column("error_message", Text),
    Column("snapshot", JSONB),
)
_platform_health = Table(
    "platform_health",
    _metadata,
    Column("platform", String(32), primary_key=True),
    Column("state", String(16), nullable=False),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_failure_at", DateTime(timezone=True)),
    Column("success_rate_24h", Numeric(5, 2)),
    Column("avg_latency_ms_24h", Integer),
    Column("consecutive_failures", Integer, nullable=False),
    Column("error_count_24h", Integer, nullable=False),
    Column("success_count_24h", Integer, nullable=False),
    Column("sustained_qps", Numeric(6, 2)),
    Column("max_anchors", Integer),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def _account_pk(account_id: str) -> int:
    try:
        value = int(account_id)
    except ValueError as exc:
        raise ValueError("account_id must be a persistence integer id") from exc
    if value < 1:
        raise ValueError("account_id must be positive")
    return value


class SQLAlchemyDetectionTelemetryRepository:
    """Append formal operational telemetry and refresh exact formal 24h metrics.

    `success_count_24h`/`error_count_24h` are recomputed from Gate 2.3-tagged
    probe_runs in the trailing 24-hour window, rather than incremented blindly.
    Existing platform-health state is preserved; Gate 2.4 owns state transitions.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record_probe(
        self,
        record: ProbeTelemetryRecord,
    ) -> ProbeTelemetryPersistenceResult:
        account_pk = _account_pk(record.account_id)
        async with self._session_factory() as session:
            async with session.begin():
                account_platform = await session.scalar(
                    select(_accounts.c.platform).where(_accounts.c.id == account_pk)
                )
                if account_platform is None:
                    raise ValueError(f"platform account {record.account_id!r} not found")
                if account_platform != record.platform:
                    raise ValueError("telemetry platform does not match platform account")

                snapshot = {
                    "telemetry_schema": TELEMETRY_SCHEMA,
                    "probe_id": record.probe_id,
                    "platform": record.platform,
                    "attempts": record.attempts,
                    "latency_ms": record.latency_ms,
                    "observation_status": record.observation_status,
                    "failure_kind": record.failure_kind,
                }
                probe_run_id = int(
                    await session.scalar(
                        insert(_probe_runs)
                        .values(
                            platform_account_id=account_pk,
                            started_at=record.started_at,
                            finished_at=record.finished_at,
                            success=record.success,
                            error_message=record.failure_kind,
                            snapshot=snapshot,
                        )
                        .returning(_probe_runs.c.id)
                    )
                )

                current = (
                    await session.execute(
                        select(_platform_health).where(
                            _platform_health.c.platform == record.platform
                        )
                    )
                ).mappings().one_or_none()

                previous_failures = 0 if current is None else int(current["consecutive_failures"])
                consecutive_failures = 0 if record.success else previous_failures + 1
                state = (
                    PlatformHealthState.HEALTHY.value
                    if current is None
                    else str(current["state"])
                )
                last_success_at = (
                    record.finished_at
                    if record.success
                    else (None if current is None else current["last_success_at"])
                )
                last_failure_at = (
                    record.finished_at
                    if not record.success
                    else (None if current is None else current["last_failure_at"])
                )

                window_start = record.finished_at - timedelta(hours=24)
                formal_filter = and_(
                    _accounts.c.platform == record.platform,
                    _probe_runs.c.finished_at >= window_start,
                    _probe_runs.c.snapshot["telemetry_schema"].astext == TELEMETRY_SCHEMA,
                )
                success_expr = func.coalesce(
                    func.sum(case((_probe_runs.c.success.is_(True), 1), else_=0)), 0
                )
                error_expr = func.coalesce(
                    func.sum(case((_probe_runs.c.success.is_(False), 1), else_=0)), 0
                )
                avg_latency_expr = func.avg(
                    cast(_probe_runs.c.snapshot["latency_ms"].astext, Integer)
                )
                aggregate = (
                    await session.execute(
                        select(
                            success_expr.label("success_count"),
                            error_expr.label("error_count"),
                            avg_latency_expr.label("avg_latency"),
                        )
                        .select_from(
                            _probe_runs.join(
                                _accounts,
                                _accounts.c.id == _probe_runs.c.platform_account_id,
                            )
                        )
                        .where(formal_filter)
                    )
                ).mappings().one()
                success_count = int(aggregate["success_count"] or 0)
                error_count = int(aggregate["error_count"] or 0)
                total_count = success_count + error_count
                success_rate = (
                    None if total_count == 0 else round(success_count * 100.0 / total_count, 2)
                )
                avg_latency = aggregate["avg_latency"]
                avg_latency_ms = None if avg_latency is None else int(round(float(avg_latency)))

                values = {
                    "state": state,
                    "last_success_at": last_success_at,
                    "last_failure_at": last_failure_at,
                    "success_rate_24h": success_rate,
                    "avg_latency_ms_24h": avg_latency_ms,
                    "consecutive_failures": consecutive_failures,
                    "error_count_24h": error_count,
                    "success_count_24h": success_count,
                    "updated_at": record.finished_at,
                }
                if current is None:
                    await session.execute(
                        insert(_platform_health).values(platform=record.platform, **values)
                    )
                else:
                    await session.execute(
                        update(_platform_health)
                        .where(_platform_health.c.platform == record.platform)
                        .values(**values)
                    )

        return ProbeTelemetryPersistenceResult(
            probe_run_id=probe_run_id,
            health=PlatformHealthSnapshot(
                platform=record.platform,
                state=PlatformHealthState(state),
                last_success_at=last_success_at,
                last_failure_at=last_failure_at,
                success_count_24h=success_count,
                error_count_24h=error_count,
                success_rate_24h=success_rate,
                avg_latency_ms_24h=avg_latency_ms,
                consecutive_failures=consecutive_failures,
            ),
        )
