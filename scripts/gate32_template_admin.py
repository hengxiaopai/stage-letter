#!/usr/bin/env python3
"""Administrative status/register/enable CLI for one WeChat template."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from stage_letter.application.services.wechat_template import (
    WeChatTemplateRegistryApplicationService,
)
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


def _template_ref(template_id: str) -> str:
    return hashlib.sha256(template_id.encode("utf-8")).hexdigest()[:12]


async def _run(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def uow_factory():
        return SQLAlchemyUnitOfWork(factory)

    service = WeChatTemplateRegistryApplicationService(uow_factory)
    try:
        if args.action == "status":
            registration = await service.get(args.template_id)
        elif args.action == "register":
            registration = await service.register(
                args.template_id,
                now=datetime.now(timezone.utc),
            )
        else:
            registration = await service.enable_by_administrator(
                args.template_id,
                administrator=args.administrator,
                now=datetime.now(timezone.utc),
            )

        payload = {
            "action": args.action,
            "template_ref": _template_ref(args.template_id),
            "registered": registration is not None,
            "effective_enabled": registration is None or registration.enabled,
            "state": None if registration is None else registration.state.value,
            "state_source": (
                None if registration is None else registration.state_source.value
            ),
            "updated_by": None if registration is None else registration.updated_by,
            "disabled_reason": (
                None if registration is None else registration.disabled_reason
            ),
            "provider_called": False,
            "live_truth_mutated": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "register", "enable"))
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--administrator")
    args = parser.parse_args()
    if args.action == "enable" and not (args.administrator or "").strip():
        parser.error("enable requires --administrator")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parse_args())))
