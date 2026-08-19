"""Read-only reconstruction of canonical reducer state from durable observations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import ObservationReplayRecord, UnitOfWork
from stage_letter.domain.state_engine import EngineConfig, EngineSnapshot, LiveStateReducer

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class StateReconstructionResult:
    """Point-in-replay reducer state rebuilt entirely from durable evidence."""

    snapshot: EngineSnapshot
    observations_replayed: int
    last_sequence: int


@dataclass(frozen=True)
class ObservationConsumptionPoint:
    """Reducer state immediately before one durable formal observation."""

    prior: StateReconstructionResult
    target: ObservationReplayRecord


class StateReconstructionApplicationService:
    """Replay formal scheduler observations in durable persistence order.

    Historical transition intents emitted during replay are intentionally not
    returned and are never persisted by this service. Gate 1.5 transition
    persistence owns writes only for a newly consumed observation.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        config: EngineConfig | None = None,
        page_size: int = 500,
    ) -> None:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        self._uow_factory = uow_factory
        self._config = config or EngineConfig()
        self._page_size = page_size

    @property
    def config(self) -> EngineConfig:
        """Expose the immutable reducer policy used during reconstruction."""

        return self._config

    async def reconstruct(self, account_id: str) -> StateReconstructionResult:
        await self._require_account(account_id)
        reducer = LiveStateReducer(config=self._config)
        after_sequence = 0
        replayed = 0

        while True:
            page = await self._read_page(account_id, after_sequence)
            if not page:
                break

            previous_sequence = after_sequence
            for record in page:
                self._validate_record(account_id, record, previous_sequence)
                reducer.process(record.observation)
                previous_sequence = record.sequence
                replayed += 1

            after_sequence = previous_sequence
            if len(page) < self._page_size:
                break

        return StateReconstructionResult(
            snapshot=reducer.snapshot(),
            observations_replayed=replayed,
            last_sequence=after_sequence,
        )

    async def reconstruct_before_observation(
        self,
        account_id: str,
        observation_id: str,
    ) -> ObservationConsumptionPoint:
        """Rebuild reducer state immediately before one durable monitor observation.

        The target itself is not replayed here. This is the key Gate 1.5-4
        boundary: historical intents are discarded, then the consumer processes
        exactly one target observation and may persist only that newly emitted
        intent.
        """

        await self._require_account(account_id)
        if not observation_id.startswith("monitor:"):
            raise ValueError("formal observation_id must use monitor: namespace")

        reducer = LiveStateReducer(config=self._config)
        after_sequence = 0
        replayed = 0

        while True:
            page = await self._read_page(account_id, after_sequence)
            if not page:
                break

            previous_sequence = after_sequence
            for record in page:
                self._validate_record(account_id, record, previous_sequence)
                if record.observation.observation_id == observation_id:
                    return ObservationConsumptionPoint(
                        prior=StateReconstructionResult(
                            snapshot=reducer.snapshot(),
                            observations_replayed=replayed,
                            last_sequence=previous_sequence,
                        ),
                        target=record,
                    )
                reducer.process(record.observation)
                previous_sequence = record.sequence
                replayed += 1

            after_sequence = previous_sequence
            if len(page) < self._page_size:
                break

        raise ApplicationNotFoundError(
            f"formal observation {observation_id!r} not found for account {account_id!r}"
        )

    async def _require_account(self, account_id: str) -> None:
        if not account_id.strip():
            raise ValueError("account_id is required")
        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {account_id!r} not found"
                )

    async def _read_page(
        self,
        account_id: str,
        after_sequence: int,
    ) -> tuple[ObservationReplayRecord, ...]:
        async with self._uow_factory() as uow:
            return await uow.live.list_monitor_observations(
                account_id,
                after_sequence=after_sequence,
                limit=self._page_size,
            )

    @staticmethod
    def _validate_record(
        account_id: str,
        record: ObservationReplayRecord,
        previous_sequence: int,
    ) -> None:
        if record.sequence <= previous_sequence:
            raise RuntimeError("observation replay sequence is not strictly increasing")
        if record.observation.account_id != account_id:
            raise RuntimeError("observation replay returned another account's evidence")
        if not record.observation.observation_id.startswith("monitor:"):
            raise RuntimeError("observation replay returned non-monitor evidence")
