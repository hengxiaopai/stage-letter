from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from api.routers.notifications import _grant_response
from stage_letter.application.services.grant_intake import (
    GrantIntakeConflictError,
    WeChatGrantApplicationService,
)
from stage_letter.domain.grant_intake import GrantIntakeDecision, WeChatGrantIntake
from stage_letter.domain.notifications import WeChatGrantLedger
from stage_letter.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


class _GrantRepository:
    def __init__(self) -> None:
        self.intakes: dict[tuple[str, str, str], WeChatGrantIntake] = {}
        self.ledgers: dict[tuple[str, str], WeChatGrantLedger] = {}
        self.increment_calls = 0

    async def create_wechat_grant_intake(self, intake: WeChatGrantIntake) -> bool:
        key = (intake.user_id, intake.request_id, intake.template_id)
        if key in self.intakes:
            return False
        self.intakes[key] = intake
        return True

    async def get_wechat_grant_intake(self, user_id, request_id, template_id):
        return self.intakes.get((user_id, request_id, template_id))

    async def get_wechat_grant(self, user_id, template_id):
        return self.ledgers.get((user_id, template_id))

    async def increment_wechat_grant(self, user_id, template_id, *, granted_at):
        del granted_at
        self.increment_calls += 1
        old = self.ledgers.get(
            (user_id, template_id), WeChatGrantLedger(user_id, template_id, 0, 0)
        )
        ledger = WeChatGrantLedger(
            user_id,
            template_id,
            old.granted_count + 1,
            old.consumed_count,
        )
        self.ledgers[(user_id, template_id)] = ledger
        return ledger


class _UoW:
    def __init__(self, grants: _GrantRepository) -> None:
        self.grants = grants
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_accept_intake_adds_exactly_one_optimistic_grant() -> None:
    grants = _GrantRepository()
    uow = _UoW(grants)
    service = WeChatGrantApplicationService(lambda: uow)  # type: ignore[arg-type]

    result = await service.record_intake(
        user_id="20",
        request_id="wx-request-001",
        results=(("tpl-live", GrantIntakeDecision.ACCEPT),),
        received_at=T0,
    )

    assert result[0].created
    assert result[0].ledger.available == 1
    assert grants.increment_calls == 1
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_exact_replay_is_idempotent_and_does_not_increment_again() -> None:
    grants = _GrantRepository()
    uow = _UoW(grants)
    service = WeChatGrantApplicationService(lambda: uow)  # type: ignore[arg-type]
    arguments = dict(
        user_id="20",
        request_id="wx-request-001",
        results=(("tpl-live", GrantIntakeDecision.ACCEPT),),
        received_at=T0,
    )

    await service.record_intake(**arguments)
    replay = await service.record_intake(**arguments)

    assert not replay[0].created
    assert replay[0].ledger.granted_count == 1
    assert grants.increment_calls == 1


@pytest.mark.asyncio
async def test_reject_and_ban_are_evidence_only() -> None:
    grants = _GrantRepository()
    uow = _UoW(grants)
    service = WeChatGrantApplicationService(lambda: uow)  # type: ignore[arg-type]

    result = await service.record_intake(
        user_id="20",
        request_id="wx-request-002",
        results=(
            ("tpl-reject", GrantIntakeDecision.REJECT),
            ("tpl-ban", GrantIntakeDecision.BAN),
        ),
        received_at=T0,
    )

    assert all(item.created for item in result)
    assert all(item.ledger.available == 0 for item in result)
    assert grants.increment_calls == 0


@pytest.mark.asyncio
async def test_same_idempotency_key_with_changed_decision_conflicts() -> None:
    grants = _GrantRepository()
    uow = _UoW(grants)
    service = WeChatGrantApplicationService(lambda: uow)  # type: ignore[arg-type]
    await service.record_intake(
        user_id="20",
        request_id="wx-request-003",
        results=(("tpl-live", GrantIntakeDecision.REJECT),),
        received_at=T0,
    )

    with pytest.raises(GrantIntakeConflictError):
        await service.record_intake(
            user_id="20",
            request_id="wx-request-003",
            results=(("tpl-live", GrantIntakeDecision.ACCEPT),),
            received_at=T0,
        )
    assert grants.increment_calls == 0


@pytest.mark.asyncio
async def test_duplicate_template_in_one_callback_is_rejected() -> None:
    service = WeChatGrantApplicationService(lambda: _UoW(_GrantRepository()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        await service.record_intake(
            user_id="20",
            request_id="wx-request-004",
            results=(
                ("tpl-live", GrantIntakeDecision.ACCEPT),
                ("tpl-live", GrantIntakeDecision.ACCEPT),
            ),
            received_at=T0,
        )


def test_user_view_clamps_provider_authoritative_ledger_drift() -> None:
    response = _grant_response("tpl-live", granted=1, consumed=2)
    assert response.available == 0
    assert response.ledger_drift_detected


def test_intake_table_stays_outside_frozen_canonical_base() -> None:
    assert "wechat_grant_intakes" not in Base.metadata.tables
    migration = (
        ROOT / "migrations" / "versions" / "d33c4e8a1b60_gate33_grant_intake.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "d33c4e8a1b60"' in migration
    assert '"user_id", "request_id", "template_id"' in migration
    assert "accept', 'reject', 'ban" in migration


def test_public_intake_contract_does_not_accept_arbitrary_counts() -> None:
    router = (ROOT / "api" / "routers" / "notifications.py").read_text(
        encoding="utf-8"
    )
    miniapp = (ROOT / "miniapp" / "services" / "notifications.js").read_text(
        encoding="utf-8"
    )
    assert "accept_count" not in router
    assert "accept_count" not in miniapp
    assert "request_id" in router and "decision" in router
