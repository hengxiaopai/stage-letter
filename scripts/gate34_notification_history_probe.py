"""Controlled PostgreSQL acceptance probe for Gate 3.4 read-model history."""
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
from api.routers.anchors import get_anchor  # noqa: E402
from stage_letter.application.services import NotificationHistoryApplicationService  # noqa: E402
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork  # noqa: E402


async def _main() -> None:
    suffix = uuid4().hex[:16]
    openid = f"gate34-probe-{suffix}"
    platform_user_id = f"gate34-account-{suffix}"
    event_prefix = f"gate34-event-{suffix}"
    now = datetime.now(timezone.utc)
    ids: dict[str, int] = {}
    cleanup_complete = False

    try:
        async with async_session() as session:
            ids["user"] = (
                await session.execute(
                    text("INSERT INTO users (openid) VALUES (:openid) RETURNING id"),
                    {"openid": openid},
                )
            ).scalar_one()
            ids["creator"] = (
                await session.execute(
                    text("INSERT INTO creators DEFAULT VALUES RETURNING id")
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO creator_profiles (creator_id, display_name) "
                    "VALUES (:creator_id, 'Gate 3.4 Probe Creator')"
                ),
                {"creator_id": ids["creator"]},
            )
            ids["account"] = (
                await session.execute(
                    text(
                        "INSERT INTO platform_accounts "
                        "(creator_id, platform, platform_user_id, is_disabled) "
                        "VALUES (:creator_id, 'bilibili', :platform_user_id, false) "
                        "RETURNING id"
                    ),
                    {
                        "creator_id": ids["creator"],
                        "platform_user_id": platform_user_id,
                    },
                )
            ).scalar_one()
            ids["session"] = (
                await session.execute(
                    text(
                        "INSERT INTO live_sessions "
                        "(platform_account_id, started_at, origin) "
                        "VALUES (:account_id, :started_at, 'TRANSITION') RETURNING id"
                    ),
                    {"account_id": ids["account"], "started_at": now},
                )
            ).scalar_one()

            delivery_ids: list[int] = []
            shapes = (
                ("IN_APP", "SENT"),
                ("WECHAT_SUBSCRIBE", "SENT"),
                ("WECHAT_SUBSCRIBE", "BLOCKED_CONFIG"),
            )
            for position, (channel, state) in enumerate(shapes, start=1):
                event_pk = (
                    await session.execute(
                        text(
                            "INSERT INTO live_events "
                            "(event_id, platform_account_id, live_session_id, event_type, "
                            "cause, occurred_at) VALUES "
                            "(:event_id, :account_id, :session_id, 'LIVE_STARTED', "
                            "'TRANSITION', :occurred_at) RETURNING id"
                        ),
                        {
                            "event_id": f"{event_prefix}-{position}",
                            "account_id": ids["account"],
                            "session_id": ids["session"],
                            "occurred_at": now,
                        },
                    )
                ).scalar_one()
                delivery_id = (
                    await session.execute(
                        text(
                            "INSERT INTO notification_deliveries "
                            "(user_id, live_event_id, live_session_id, channel, state, "
                            "attempt, updated_at) VALUES "
                            "(:user_id, :event_id, :session_id, :channel, :state, 0, :now) "
                            "RETURNING id"
                        ),
                        {
                            "user_id": ids["user"],
                            "event_id": event_pk,
                            "session_id": ids["session"],
                            "channel": channel,
                            "state": state,
                            "now": now,
                        },
                    )
                ).scalar_one()
                delivery_ids.append(delivery_id)
            await session.commit()

        service = NotificationHistoryApplicationService(
            lambda: SQLAlchemyUnitOfWork(async_session)
        )
        first = await service.list_for_user(str(ids["user"]), limit=2)
        second = await service.list_for_user(
            str(ids["user"]), limit=2, cursor=first.next_cursor
        )

        async with async_session() as session:
            detail = await get_anchor(ids["creator"], session)
            migration_head = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            index_present = bool(
                (
                    await session.execute(
                        text(
                            "SELECT 1 FROM pg_indexes "
                            "WHERE tablename = 'notification_deliveries' "
                            "AND indexname = 'idx_g34_delivery_user_history'"
                        )
                    )
                ).scalar_one_or_none()
            )

        checks = {
            "migration_head_matches": migration_head == "e34d7a2c1b50",
            "history_index_present": index_present,
            "first_page_is_newest_first": [item.delivery_id for item in first.items]
            == list(reversed(delivery_ids[-2:])),
            "keyset_cursor_is_last_visible_id": first.next_cursor
            == str(delivery_ids[1]),
            "second_page_has_no_duplicate": [item.delivery_id for item in second.items]
            == [delivery_ids[0]],
            "profile_and_platform_joined": all(
                item.display_name == "Gate 3.4 Probe Creator"
                and item.platform == "bilibili"
                for item in (*first.items, *second.items)
            ),
            "detail_target_is_canonical": all(
                item.target.miniapp_path
                == f"pages/detail/index?id={ids['creator']}"
                for item in (*first.items, *second.items)
            ),
            "formal_detail_target_resolves": (
                detail.id == ids["creator"]
                and detail.display_name == "Gate 3.4 Probe Creator"
                and detail.platforms[0].live_state == "LIVE"
            ),
        }
    finally:
        if ids:
            async with async_session() as session:
                if "user" in ids:
                    await session.execute(
                        text("DELETE FROM notification_deliveries WHERE user_id = :user_id"),
                        {"user_id": ids["user"]},
                    )
                if "account" in ids:
                    await session.execute(
                        text("DELETE FROM live_events WHERE platform_account_id = :account_id"),
                        {"account_id": ids["account"]},
                    )
                    await session.execute(
                        text("DELETE FROM live_sessions WHERE platform_account_id = :account_id"),
                        {"account_id": ids["account"]},
                    )
                    await session.execute(
                        text("DELETE FROM platform_accounts WHERE id = :account_id"),
                        {"account_id": ids["account"]},
                    )
                if "creator" in ids:
                    await session.execute(
                        text("DELETE FROM creator_profiles WHERE creator_id = :creator_id"),
                        {"creator_id": ids["creator"]},
                    )
                    await session.execute(
                        text("DELETE FROM creators WHERE id = :creator_id"),
                        {"creator_id": ids["creator"]},
                    )
                if "user" in ids:
                    await session.execute(
                        text("DELETE FROM users WHERE id = :user_id"),
                        {"user_id": ids["user"]},
                    )
                await session.commit()
                remaining = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM users WHERE openid = :openid"
                        ),
                        {"openid": openid},
                    )
                ).scalar_one()
                cleanup_complete = remaining == 0

    checks["cleanup_complete"] = cleanup_complete
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        json.dumps(
            {
                "gate": "3.4",
                "probe": "postgresql_notification_history_keyset",
                "status": status,
                "migration_head": migration_head,
                "checks": checks,
                "provider_called": False,
                "notification_sent": False,
                "user_read_claimed": False,
                "live_truth_mutated": False,
                "database_restored": cleanup_complete,
                "production_approved": False,
            },
            indent=2,
        )
    )
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_main())
