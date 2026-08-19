"""One-account monitoring probe orchestration for Gate 1.4-2.

This service bridges an already-formal LivePlatformAdapter snapshot into one
durable LiveObservation. Provider I/O happens outside database transactions.
Scheduler cadence/concurrency/backoff remain Gate 1.4-3 concerns.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.errors import (
    ApplicationInvariantError,
    ApplicationNotFoundError,
)
from stage_letter.application.platforms import LivePlatformAdapter, LiveSnapshot
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.live import LiveObservation

UnitOfWorkFactory = Callable[[], UnitOfWork]
AdapterLookup = Callable[[str], LivePlatformAdapter]


@dataclass(frozen=True)
class MonitoringProbeRequest:
    """One logical probe request for one formal platform account.

    A scheduler/retry mechanism must reuse the same probe_id when retrying the
    same logical request. Gate 1.4 stores that probe_id directly as the durable
    observation_id, scoped by account.
    """

    probe_id: str
    account_id: str

    def __post_init__(self) -> None:
        if not self.probe_id.strip():
            raise ValueError("probe_id is required")
        if len(self.probe_id) > 255:
            raise ValueError("probe_id must fit live_observations.observation_id")
        if not self.account_id.strip():
            raise ValueError("account_id is required")


@dataclass(frozen=True)
class MonitoringProbeResult:
    observation: LiveObservation
    reused_existing: bool


class MonitoringProbeApplicationService:
    """Run one provider probe and persist one normalized observation fact."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        adapter_lookup: AdapterLookup,
    ) -> None:
        self._uow_factory = uow_factory
        self._adapter_lookup = adapter_lookup

    async def execute(self, request: MonitoringProbeRequest) -> MonitoringProbeResult:
        # Read-side idempotency and eligibility check. No provider work is allowed
        # while this transaction boundary is open.
        async with self._uow_factory() as uow:
            existing = await uow.live.get_observation(
                request.account_id,
                request.probe_id,
            )
            if existing is not None:
                return MonitoringProbeResult(existing, reused_existing=True)

            account = await uow.creators.get_account(request.account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {request.account_id!r} not found"
                )
            if not account.enabled:
                raise ApplicationInvariantError(
                    f"platform account {request.account_id!r} is not enabled for monitoring"
                )

        adapter = self._adapter_lookup(account.platform)
        if not isinstance(adapter, LivePlatformAdapter):
            raise ApplicationInvariantError(
                f"adapter lookup returned an invalid adapter for {account.platform!r}"
            )

        # Provider I/O is deliberately outside the UnitOfWork.
        snapshot = await adapter.get_live_snapshot(account)
        self._validate_snapshot_identity(account.platform, account.platform_user_id, snapshot)

        observation = LiveObservation(
            observation_id=request.probe_id,
            account_id=account.account_id,
            status=snapshot.status,
            observed_at=snapshot.observed_at,
            source=snapshot.source,
            source_started_at=snapshot.source_started_at,
        )

        # Re-check after provider I/O so a sequential retry, or another worker that
        # completed while this provider call was in flight, can reuse durable work.
        # Gate 1.4-3 owns concurrent single-flight/lease semantics.
        async with self._uow_factory() as uow:
            existing = await uow.live.get_observation(
                request.account_id,
                request.probe_id,
            )
            if existing is not None:
                return MonitoringProbeResult(existing, reused_existing=True)

            current = await uow.creators.get_account(request.account_id)
            if current is None:
                raise ApplicationNotFoundError(
                    f"platform account {request.account_id!r} disappeared before persistence"
                )
            if (
                current.platform != account.platform
                or current.platform_user_id != account.platform_user_id
            ):
                raise ApplicationInvariantError(
                    "platform account identity changed while probe was in flight"
                )

            await uow.live.append_observation(observation)
            await uow.commit()

        return MonitoringProbeResult(observation, reused_existing=False)

    @staticmethod
    def _validate_snapshot_identity(
        platform: str,
        platform_user_id: str,
        snapshot: LiveSnapshot,
    ) -> None:
        if snapshot.platform != platform:
            raise ApplicationInvariantError(
                "live snapshot platform does not match requested account"
            )
        if snapshot.platform_user_id != platform_user_id:
            raise ApplicationInvariantError(
                "live snapshot provider identity does not match requested account"
            )
