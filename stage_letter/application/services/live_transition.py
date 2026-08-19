"""Atomic LiveSession / LiveEvent persistence for one reducer transition intent."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from stage_letter.application.errors import ApplicationInvariantError, ApplicationNotFoundError
from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.live import (
    LiveEvent,
    LiveEventCause,
    LiveEventType,
    LiveObservation,
    LiveSession,
    LiveStatus,
)
from stage_letter.domain.state_engine import TransitionIntent, TransitionIntentType

UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True)
class TransitionPersistenceResult:
    session: LiveSession
    event: LiveEvent
    reused_existing: bool


def make_live_event_id(
    account_id: str,
    observation_id: str,
    event_type: LiveEventType,
) -> str:
    """Return a deterministic bounded string event id; session ids remain DB-owned."""

    account = account_id.strip()
    observation = observation_id.strip()
    if not account:
        raise ValueError("account_id is required")
    if not observation.startswith("monitor:"):
        raise ValueError("formal transition events require a monitor: observation id")
    digest = hashlib.sha256(
        f"{account}\0{observation}\0{event_type.value}".encode("utf-8")
    ).hexdigest()
    return f"live-event:{digest}"


class LiveTransitionPersistenceApplicationService:
    """Atomically apply one already-decided reducer transition intent.

    Canonical session/event mutation is serialized per account through the
    persistence port. This closes cross-process duplicate state-output races while
    preserving the weaker, accurate claim: worker/provider execution itself is
    not exactly once.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def apply(
        self,
        observation: LiveObservation,
        intent: TransitionIntent,
    ) -> TransitionPersistenceResult:
        event_type = self._validate_intent(observation, intent)
        event_id = make_live_event_id(
            observation.account_id,
            observation.observation_id,
            event_type,
        )

        async with self._uow_factory() as uow:
            account = await uow.creators.get_account(observation.account_id)
            if account is None:
                raise ApplicationNotFoundError(
                    f"platform account {observation.account_id!r} not found"
                )

            # The transaction-scoped per-account lock is acquired before any
            # existing-event/session decision. A concurrent consumer therefore
            # waits, then observes the canonical winner after the first commit.
            await uow.live.acquire_transition_lock(observation.account_id)

            durable = await uow.live.get_observation(
                observation.account_id,
                observation.observation_id,
            )
            if durable is None:
                raise ApplicationNotFoundError(
                    f"durable observation {observation.observation_id!r} not found"
                )
            if durable != observation:
                raise ApplicationInvariantError(
                    "transition input does not match the durable observation"
                )

            existing_event = await uow.live.get_event(event_id)
            if existing_event is not None:
                session = await uow.live.get_session(existing_event.session_id)
                if session is None:
                    raise ApplicationInvariantError(
                        "persisted live event references a missing formal session"
                    )
                self._validate_existing(
                    observation,
                    intent,
                    session,
                    existing_event,
                    event_type,
                )
                return TransitionPersistenceResult(session, existing_event, True)

            if intent.intent_type is TransitionIntentType.OPEN_SESSION:
                if await uow.live.get_open_session(observation.account_id) is not None:
                    raise ApplicationInvariantError(
                        "OPEN_SESSION intent encountered an existing open session"
                    )
                assert intent.origin is not None
                session = await uow.live.create_session(
                    observation.account_id,
                    opened_at=intent.occurred_at,
                    origin=intent.origin,
                    source_started_at=intent.source_started_at,
                )
            else:
                open_session = await uow.live.get_open_session(observation.account_id)
                if open_session is None:
                    raise ApplicationInvariantError(
                        "CLOSE_SESSION intent requires one open session"
                    )
                if intent.occurred_at < open_session.opened_at:
                    raise ApplicationInvariantError(
                        "session close cannot precede its persisted open time"
                    )
                session = LiveSession(
                    session_id=open_session.session_id,
                    account_id=open_session.account_id,
                    opened_at=open_session.opened_at,
                    origin=open_session.origin,
                    closed_at=intent.occurred_at,
                    source_started_at=open_session.source_started_at,
                )
                await uow.live.save_session(session)

            event = LiveEvent(
                event_id=event_id,
                account_id=observation.account_id,
                session_id=session.session_id,
                event_type=event_type,
                cause=intent.cause,
                occurred_at=intent.occurred_at,
            )
            inserted = await uow.live.append_event(event)
            if not inserted:
                raise ApplicationInvariantError(
                    "live event identity was concurrently claimed during serialized transition"
                )

            await uow.commit()
            return TransitionPersistenceResult(session, event, False)

    @staticmethod
    def _validate_intent(
        observation: LiveObservation,
        intent: TransitionIntent,
    ) -> LiveEventType:
        if not observation.observation_id.startswith("monitor:"):
            raise ApplicationInvariantError(
                "formal transition persistence requires monitor: observation evidence"
            )
        if intent.occurred_at != observation.observed_at:
            raise ApplicationInvariantError(
                "transition occurred_at must equal its decisive observation timestamp"
            )

        if intent.intent_type is TransitionIntentType.OPEN_SESSION:
            if observation.status is not LiveStatus.LIVE:
                raise ApplicationInvariantError("OPEN_SESSION requires decisive LIVE evidence")
            if intent.origin is None:
                raise ApplicationInvariantError("OPEN_SESSION intent requires origin")
            expected_cause = (
                LiveEventCause.BOOTSTRAP_LIVE
                if intent.origin.value == "BOOTSTRAP_LIVE"
                else LiveEventCause.TRANSITION
            )
            if intent.cause is not expected_cause:
                raise ApplicationInvariantError(
                    "OPEN_SESSION cause does not match session origin"
                )
            if intent.source_started_at != observation.source_started_at:
                raise ApplicationInvariantError(
                    "OPEN_SESSION source_started_at must come from the decisive observation"
                )
            return LiveEventType.LIVE_STARTED

        if observation.status is not LiveStatus.OFFLINE:
            raise ApplicationInvariantError("CLOSE_SESSION requires decisive OFFLINE evidence")
        if intent.cause is not LiveEventCause.TRANSITION:
            raise ApplicationInvariantError("CLOSE_SESSION cause must be TRANSITION")
        if intent.origin is not None or intent.source_started_at is not None:
            raise ApplicationInvariantError(
                "CLOSE_SESSION must not carry open-session provenance"
            )
        return LiveEventType.LIVE_ENDED

    @staticmethod
    def _validate_existing(
        observation: LiveObservation,
        intent: TransitionIntent,
        session: LiveSession,
        event: LiveEvent,
        event_type: LiveEventType,
    ) -> None:
        if event.account_id != observation.account_id:
            raise ApplicationInvariantError("existing event belongs to another account")
        if event.event_type is not event_type:
            raise ApplicationInvariantError("existing event type conflicts with transition")
        if event.cause is not intent.cause or event.occurred_at != intent.occurred_at:
            raise ApplicationInvariantError("existing event provenance conflicts with transition")
        if session.account_id != observation.account_id:
            raise ApplicationInvariantError("existing event session belongs to another account")

        if event_type is LiveEventType.LIVE_STARTED:
            if session.opened_at != intent.occurred_at or session.origin is not intent.origin:
                raise ApplicationInvariantError("existing opened session conflicts with transition")
            if session.source_started_at != intent.source_started_at:
                raise ApplicationInvariantError(
                    "existing session source start conflicts with transition"
                )
        elif session.closed_at != intent.occurred_at:
            raise ApplicationInvariantError("existing closed session conflicts with transition")
