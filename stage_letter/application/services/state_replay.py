"""Read-only reconstruction of canonical reducer state from durable observations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.state_engine import EngineConfig, EngineSnapshot, LiveStateReducer

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class StateReconstructionResult:
    """Point-in-replay reducer state rebuilt entirely from durable evidence."""

    snapshot: EngineSnapshot
    observations_replayed: int
    last_sequence: int


class StateReconstructionApplicationService:
    """Replay formal scheduler observations in durable persistence order.

    Historical transition intents emitted during replay are intentionally not
    returned and are never persisted by this service. Gate 1.5-3 owns atomic
    session/event writes for newly consumed observations.
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

    async def reconstruct(self, account_id: str) -> StateReconstructionResult:
        if not account_id.strip():
            raise ValueError("account_id is required")

        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {account_id!r} not found"
                )

        reducer = LiveStateReducer(config=self._config)
        after_sequence = 0
        replayed = 0

        while True:
            async with self._uow_factory() as uow:
                page = await uow.live.list_monitor_observations(
                    account_id,
                    after_sequence=after_sequence,
                    limit=self._page_size,
                )

            if not page:
                break

            previous_sequence = after_sequence
            for record in page:
                if record.sequence <= previous_sequence:
                    raise RuntimeError("observation replay sequence is not strictly increasing")
                if record.observation.account_id != account_id:
                    raise RuntimeError("observation replay returned another account's evidence")
                if not record.observation.observation_id.startswith("monitor:"):
                    raise RuntimeError("observation replay returned non-monitor evidence")

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
