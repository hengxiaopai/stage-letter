"""Formal WeChat grant intake and optimistic-ledger read service."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from stage_letter.application.ports import UnitOfWork
from stage_letter.domain.grant_intake import GrantIntakeDecision, WeChatGrantIntake
from stage_letter.domain.notifications import WeChatGrantLedger

UnitOfWorkFactory = Callable[[], UnitOfWork]


class GrantIntakeConflictError(ValueError):
    """The same durable idempotency key was reused with another decision."""


@dataclass(frozen=True)
class GrantIntakeResult:
    intake: WeChatGrantIntake
    created: bool
    ledger: WeChatGrantLedger


class WeChatGrantApplicationService:
    """Record client callback evidence without pretending it is provider truth."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get_ledger(self, user_id: str, template_id: str) -> WeChatGrantLedger:
        self._validate_identity(user_id, template_id)
        async with self._uow_factory() as uow:
            ledger = await uow.grants.get_wechat_grant(user_id, template_id)
        return ledger or WeChatGrantLedger(user_id, template_id, 0, 0)

    async def record_intake(
        self,
        *,
        user_id: str,
        request_id: str,
        results: Sequence[tuple[str, GrantIntakeDecision]],
        received_at: datetime,
    ) -> tuple[GrantIntakeResult, ...]:
        if not results:
            raise ValueError("at least one grant result is required")
        if len(results) > 5:
            raise ValueError("at most five grant results are allowed")
        template_ids = [template_id for template_id, _ in results]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("template_id must be unique within one request")

        intakes = tuple(
            WeChatGrantIntake(
                user_id=user_id,
                request_id=request_id,
                template_id=template_id,
                decision=decision,
                received_at=received_at,
            )
            for template_id, decision in results
        )
        outcomes: list[GrantIntakeResult] = []
        async with self._uow_factory() as uow:
            for intake in intakes:
                created = await uow.grants.create_wechat_grant_intake(intake)
                if not created:
                    existing = await uow.grants.get_wechat_grant_intake(
                        intake.user_id,
                        intake.request_id,
                        intake.template_id,
                    )
                    if existing is None or existing.decision is not intake.decision:
                        raise GrantIntakeConflictError(
                            "grant intake idempotency key has conflicting evidence"
                        )
                elif intake.decision is GrantIntakeDecision.ACCEPT:
                    await uow.grants.increment_wechat_grant(
                        intake.user_id,
                        intake.template_id,
                        granted_at=intake.received_at,
                    )

                ledger = await uow.grants.get_wechat_grant(
                    intake.user_id,
                    intake.template_id,
                )
                outcomes.append(
                    GrantIntakeResult(
                        intake=intake,
                        created=created,
                        ledger=ledger
                        or WeChatGrantLedger(
                            intake.user_id,
                            intake.template_id,
                            0,
                            0,
                        ),
                    )
                )
            await uow.commit()
        return tuple(outcomes)

    @staticmethod
    def _validate_identity(user_id: str, template_id: str) -> None:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if not template_id.strip():
            raise ValueError("template_id is required")
