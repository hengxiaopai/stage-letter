"""Consume one durable formal observation through reconstruction and persistence."""
from __future__ import annotations

from dataclasses import dataclass

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.services.live_transition import (
    LiveTransitionPersistenceApplicationService,
    TransitionPersistenceResult,
)
from stage_letter.application.services.state_replay import (
    StateReconstructionApplicationService,
)
from stage_letter.domain.live import LiveObservation
from stage_letter.domain.state_engine import LiveStateReducer, ProcessResult


@dataclass(frozen=True)
class LiveObservationConsumptionResult:
    """Outcome of consuming exactly one durable formal monitoring observation."""

    observation: LiveObservation
    process_result: ProcessResult
    prior_observations_replayed: int
    transition: TransitionPersistenceResult | None

    @property
    def emitted_transition(self) -> bool:
        return self.transition is not None


class LiveObservationConsumptionApplicationService:
    """Reconstruct prior state, process one target fact, persist only its new intent.

    The service never replays historical transition intents into persistence. A
    retry reconstructs the same pre-target state and emits the same deterministic
    intent; transition persistence then reuses the already-persisted event/session.
    Observations that emit no intent remain read-only.
    """

    def __init__(
        self,
        reconstruction: StateReconstructionApplicationService,
        transitions: LiveTransitionPersistenceApplicationService,
    ) -> None:
        self._reconstruction = reconstruction
        self._transitions = transitions

    async def consume(
        self,
        account_id: str,
        observation_id: str,
    ) -> LiveObservationConsumptionResult:
        point = await self._reconstruction.reconstruct_before_observation(
            account_id,
            observation_id,
        )

        reducer = LiveStateReducer.from_snapshot(
            point.prior.snapshot,
            config=self._reconstruction.config,
        )
        process_result = reducer.process(point.target.observation)

        if len(process_result.emitted_intents) > 1:
            raise ApplicationInvariantError(
                "one durable observation emitted more than one transition intent"
            )

        transition: TransitionPersistenceResult | None = None
        if process_result.emitted_intents:
            transition = await self._transitions.apply(
                point.target.observation,
                process_result.emitted_intents[0],
            )

        return LiveObservationConsumptionResult(
            observation=point.target.observation,
            process_result=process_result,
            prior_observations_replayed=point.prior.observations_replayed,
            transition=transition,
        )
