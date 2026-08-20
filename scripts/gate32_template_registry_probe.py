#!/usr/bin/env python3
"""Controlled PostgreSQL acceptance for Gate 3.2 template state transitions."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.application.services.wechat_template import (
    WeChatTemplateRegistryApplicationService,
)
from stage_letter.domain.notification_templates import (
    WeChatTemplateState,
    WeChatTemplateStateSource,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork

EXPECTED_HEAD = "c32a1d7e9b40"


async def _main() -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    template_id = f"gate32-probe-{uuid4().hex}"
    payload: dict[str, object] | None = None
    exit_code = 1

    def uow_factory():
        return SQLAlchemyUnitOfWork(factory)

    service = WeChatTemplateRegistryApplicationService(uow_factory)
    try:
        async with engine.connect() as connection:
            head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if head != EXPECTED_HEAD:
            raise RuntimeError(f"migration head {head!r} != {EXPECTED_HEAD!r}")

        registered = await service.register(template_id, now=datetime.now(timezone.utc))
        disabled = await service.disable_from_40037(
            template_id,
            now=datetime.now(timezone.utc),
        )
        restarted_service = WeChatTemplateRegistryApplicationService(uow_factory)
        observed_disabled = await restarted_service.get(template_id)
        enabled = await restarted_service.enable_by_administrator(
            template_id,
            administrator="gate32-probe",
            now=datetime.now(timezone.utc),
        )

        checks = {
            "registered_enabled": registered.state is WeChatTemplateState.ENABLED,
            "provider_40037_disabled": (
                disabled.state is WeChatTemplateState.DISABLED
                and disabled.state_source is WeChatTemplateStateSource.PROVIDER_40037
            ),
            "restart_observed_disabled": (
                observed_disabled is not None
                and observed_disabled.state is WeChatTemplateState.DISABLED
            ),
            "administrator_reenabled": (
                enabled.state is WeChatTemplateState.ENABLED
                and enabled.state_source is WeChatTemplateStateSource.ADMINISTRATOR
                and enabled.disabled_reason is None
                and enabled.disabled_at is None
            ),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        exit_code = 0 if status == "PASS" else 1
        payload = {
            "gate": "3.2",
            "probe": "postgresql_wechat_template_registry",
            "status": status,
            "migration_head": head,
            "checks": checks,
            "provider_called": False,
            "notification_sent": False,
            "live_truth_mutated": False,
        }
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM wechat_notification_templates "
                    "WHERE template_id = :template_id"
                ),
                {"template_id": template_id},
            )
        async with engine.connect() as connection:
            remaining = await connection.scalar(
                text(
                    "SELECT count(*) FROM wechat_notification_templates "
                    "WHERE template_id = :template_id"
                ),
                {"template_id": template_id},
            )
        await engine.dispose()
    if payload is None:
        raise RuntimeError("Gate 3.2 probe did not produce an acceptance result")
    payload["cleanup_complete"] = remaining == 0
    payload["database_restored"] = remaining == 0
    if remaining != 0:
        payload["status"] = "FAIL"
        exit_code = 1
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
