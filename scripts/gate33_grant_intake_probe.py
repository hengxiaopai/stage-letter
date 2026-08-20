"""Controlled PostgreSQL acceptance probe for Gate 3.3.

Creates only synthetic user/grant evidence, performs no provider call, and
removes every synthetic row before reporting PASS.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import async_session  # noqa: E402
from stage_letter.application.services import (  # noqa: E402
    GrantIntakeConflictError,
    WeChatGrantApplicationService,
)
from stage_letter.domain.grant_intake import GrantIntakeDecision  # noqa: E402
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork  # noqa: E402


async def _main() -> None:
    suffix = uuid4().hex[:16]
    openid = f"gate33-probe-{suffix}"
    template_id = f"gate33-template-{suffix}"
    now = datetime.now(timezone.utc)
    user_id: int | None = None
    conflict_rejected = False
    cleanup_complete = False

    def service() -> WeChatGrantApplicationService:
        return WeChatGrantApplicationService(lambda: SQLAlchemyUnitOfWork(async_session))

    try:
        async with async_session() as session:
            user_id = (
                await session.execute(
                    text("INSERT INTO users (openid) VALUES (:openid) RETURNING id"),
                    {"openid": openid},
                )
            ).scalar_one()
            await session.commit()

        first = await service().record_intake(
            user_id=str(user_id),
            request_id="gate33-request-accept",
            results=((template_id, GrantIntakeDecision.ACCEPT),),
            received_at=now,
        )
        replay = await service().record_intake(
            user_id=str(user_id),
            request_id="gate33-request-accept",
            results=((template_id, GrantIntakeDecision.ACCEPT),),
            received_at=now,
        )
        rejected = await service().record_intake(
            user_id=str(user_id),
            request_id="gate33-request-reject",
            results=((template_id, GrantIntakeDecision.REJECT),),
            received_at=now,
        )
        try:
            await service().record_intake(
                user_id=str(user_id),
                request_id="gate33-request-reject",
                results=((template_id, GrantIntakeDecision.ACCEPT),),
                received_at=now,
            )
        except GrantIntakeConflictError:
            conflict_rejected = True

        restarted_ledger = await service().get_ledger(str(user_id), template_id)
        async with async_session() as session:
            intake_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM wechat_grant_intakes "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            ).scalar_one()
            migration_head = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()

        checks = {
            "migration_head_matches": migration_head == "d33c4e8a1b60",
            "accept_recorded": first[0].created,
            "accept_added_one": first[0].ledger.granted_count == 1,
            "exact_replay_reused": not replay[0].created,
            "replay_did_not_increment": replay[0].ledger.granted_count == 1,
            "reject_recorded_without_increment": (
                rejected[0].created and rejected[0].ledger.granted_count == 1
            ),
            "conflicting_replay_rejected": conflict_rejected,
            "restart_preserved_ledger": restarted_ledger.granted_count == 1,
            "two_durable_evidence_rows": intake_count == 2,
        }
    finally:
        if user_id is not None:
            async with async_session() as session:
                await session.execute(
                    text("DELETE FROM wechat_grant_intakes WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                await session.execute(
                    text("DELETE FROM wechat_subscription_grants WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                await session.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
                await session.commit()
                remaining = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM users WHERE id = :user_id OR openid = :openid"
                        ),
                        {"user_id": user_id, "openid": openid},
                    )
                ).scalar_one()
                cleanup_complete = remaining == 0

    checks["cleanup_complete"] = cleanup_complete
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        json.dumps(
            {
                "gate": "3.3",
                "probe": "postgresql_grant_intake_reconciliation",
                "status": status,
                "migration_head": migration_head,
                "checks": checks,
                "provider_called": False,
                "notification_called": False,
                "live_truth_mutated": False,
                "database_restored": cleanup_complete,
                "provider_balance_query_claimed": False,
                "exactly_once_claimed": False,
                "production_approved": False,
            },
            indent=2,
        )
    )
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_main())
