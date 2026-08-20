"""Controlled PostgreSQL restart/fallback/E2E acceptance probe for Gate 3.5."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import async_session  # noqa: E402
from stage_letter.application.services import (  # noqa: E402
    InAppFallbackApplicationService,
    MultiChannelNotificationEnqueueApplicationService,
    NotificationDeliveryApplicationService,
    NotificationHistoryApplicationService,
)
from stage_letter.domain.notifications import DeliveryChannel, DeliveryKey, DeliveryState  # noqa: E402
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork  # noqa: E402
from workers.notification_runtime import InAppNotificationRuntime  # noqa: E402


def _uow_factory() -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork(async_session)


async def _main() -> None:
    suffix = uuid4().hex[:16]
    template_id = f"gate35-template-{suffix}"
    event_id = f"gate35-event-{suffix}"
    account_identity = f"gate35-account-{suffix}"
    openids = (f"gate35-inapp-{suffix}", f"gate35-wechat-{suffix}")
    now = datetime.now(timezone.utc)
    event_at = now + timedelta(seconds=1)
    claim_at = event_at + timedelta(seconds=1)
    restart_at = claim_at + timedelta(seconds=120)
    ids: dict[str, int] = {}
    cleanup_complete = False

    try:
        async with async_session() as session:
            ids["user_inapp"] = (
                await session.execute(
                    text("INSERT INTO users (openid) VALUES (:openid) RETURNING id"),
                    {"openid": openids[0]},
                )
            ).scalar_one()
            ids["user_wechat"] = (
                await session.execute(
                    text("INSERT INTO users (openid) VALUES (:openid) RETURNING id"),
                    {"openid": openids[1]},
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
                    "VALUES (:creator_id, 'Gate 3.5 E2E Creator')"
                ),
                {"creator_id": ids["creator"]},
            )
            ids["account"] = (
                await session.execute(
                    text(
                        "INSERT INTO platform_accounts "
                        "(creator_id, platform, platform_user_id, is_disabled) "
                        "VALUES (:creator_id, 'bilibili', :identity, false) RETURNING id"
                    ),
                    {"creator_id": ids["creator"], "identity": account_identity},
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
            ids["event"] = (
                await session.execute(
                    text(
                        "INSERT INTO live_events "
                        "(event_id, platform_account_id, live_session_id, event_type, "
                        "cause, occurred_at) VALUES "
                        "(:event_id, :account_id, :session_id, 'LIVE_STARTED', "
                        "'TRANSITION', :occurred_at) RETURNING id"
                    ),
                    {
                        "event_id": event_id,
                        "account_id": ids["account"],
                        "session_id": ids["session"],
                        "occurred_at": event_at,
                    },
                )
            ).scalar_one()
            for user_id in (ids["user_inapp"], ids["user_wechat"]):
                await session.execute(
                    text(
                        "INSERT INTO follows "
                        "(user_id, creator_id, platform_account_id, starred, created_at) "
                        "VALUES (:user_id, :creator_id, :account_id, false, :created_at)"
                    ),
                    {
                        "user_id": user_id,
                        "creator_id": ids["creator"],
                        "account_id": ids["account"],
                        "created_at": now,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO notification_preferences "
                        "(user_id, platform_account_id, enabled) "
                        "VALUES (:user_id, :account_id, true)"
                    ),
                    {"user_id": user_id, "account_id": ids["account"]},
                )
            await session.execute(
                text(
                    "INSERT INTO wechat_subscription_grants "
                    "(user_id, template_id, granted_count, consumed_count) "
                    "VALUES (:user_id, :template_id, 1, 0)"
                ),
                {"user_id": ids["user_wechat"], "template_id": template_id},
            )
            await session.commit()

        enqueue = MultiChannelNotificationEnqueueApplicationService(_uow_factory)
        enqueue_result = await enqueue.enqueue_live_event(
            event_id=event_id,
            template_id=template_id,
        )

        worker_a = NotificationDeliveryApplicationService(
            _uow_factory,
            channel=DeliveryChannel.WECHAT_SUBSCRIBE,
        )
        worker_b = NotificationDeliveryApplicationService(
            _uow_factory,
            channel=DeliveryChannel.WECHAT_SUBSCRIBE,
        )
        claims = await asyncio.gather(
            worker_a.claim_next_due(now=claim_at),
            worker_b.claim_next_due(now=claim_at),
        )
        winners = tuple(claim for claim in claims if claim is not None)

        restarted_worker = NotificationDeliveryApplicationService(
            _uow_factory,
            channel=DeliveryChannel.WECHAT_SUBSCRIBE,
        )
        recovery = await restarted_worker.recover_stale_in_flight(
            now=restart_at,
            stale_after_seconds=60,
        )
        wechat_key = DeliveryKey(
            str(ids["user_wechat"]),
            event_id,
            DeliveryChannel.WECHAT_SUBSCRIBE,
        )
        async with _uow_factory() as uow:
            recovered_wechat = await uow.notifications.get_delivery(wechat_key)

        fallback_service = InAppFallbackApplicationService(_uow_factory)
        fallback_first = await fallback_service.ensure_for_wechat(recovered_wechat)
        fallback_replay = await fallback_service.ensure_for_wechat(recovered_wechat)

        in_app_runtime = InAppNotificationRuntime(uow_factory=_uow_factory)
        in_app_runs = (
            await in_app_runtime.run_once(now=restart_at + timedelta(seconds=1)),
            await in_app_runtime.run_once(now=restart_at + timedelta(seconds=1)),
            await in_app_runtime.run_once(now=restart_at + timedelta(seconds=1)),
        )

        history = NotificationHistoryApplicationService(_uow_factory)
        inapp_history = await history.list_for_user(str(ids["user_inapp"]), limit=10)
        wechat_history = await history.list_for_user(str(ids["user_wechat"]), limit=10)

        async with async_session() as session:
            migration_head = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            grant_counts = (
                await session.execute(
                    text(
                        "SELECT granted_count, consumed_count "
                        "FROM wechat_subscription_grants "
                        "WHERE user_id = :user_id AND template_id = :template_id"
                    ),
                    {"user_id": ids["user_wechat"], "template_id": template_id},
                )
            ).one()
            session_closed_at = (
                await session.execute(
                    text("SELECT ended_at FROM live_sessions WHERE id = :session_id"),
                    {"session_id": ids["session"]},
                )
            ).scalar_one()
            event_count = (
                await session.execute(
                    text("SELECT count(*) FROM live_events WHERE event_id = :event_id"),
                    {"event_id": event_id},
                )
            ).scalar_one()

        checks = {
            "migration_head_unchanged": migration_head == "e34d7a2c1b50",
            "fanout_examined_two": enqueue_result.examined == 2,
            "fanout_created_two_channels": enqueue_result.created == 2,
            "multiworker_single_claim_winner": len(winners) == 1,
            "restart_recovered_one_ambiguous": recovery.recovered_ambiguous == 1,
            "wechat_recovery_is_ambiguous": (
                recovered_wechat is not None
                and recovered_wechat.state is DeliveryState.AMBIGUOUS
            ),
            "fallback_created_once": (
                fallback_first is not None
                and fallback_first.created
                and fallback_replay is not None
                and not fallback_replay.created
            ),
            "two_in_app_deliveries_sent_then_idle": (
                [run.action for run in in_app_runs] == ["SENT", "SENT", "IDLE"]
            ),
            "grant_not_consumed_without_provider": tuple(grant_counts) == (1, 0),
            "direct_in_app_history_visible": (
                len(inapp_history.items) == 1
                and inapp_history.items[0].channel is DeliveryChannel.IN_APP
                and inapp_history.items[0].state is DeliveryState.SENT
            ),
            "wechat_and_fallback_history_visible": (
                len(wechat_history.items) == 2
                and {item.channel for item in wechat_history.items}
                == {DeliveryChannel.WECHAT_SUBSCRIBE, DeliveryChannel.IN_APP}
                and {item.state for item in wechat_history.items}
                == {DeliveryState.AMBIGUOUS, DeliveryState.SENT}
            ),
            "history_targets_creator_detail": all(
                item.target.miniapp_path
                == f"pages/detail/index?id={ids['creator']}"
                for item in (*inapp_history.items, *wechat_history.items)
            ),
            "live_truth_preserved": session_closed_at is None and event_count == 1,
        }
    finally:
        if ids:
            async with async_session() as session:
                if "user_inapp" in ids and "user_wechat" in ids:
                    await session.execute(
                        text(
                            "DELETE FROM notification_deliveries "
                            "WHERE user_id IN (:user_inapp, :user_wechat)"
                        ),
                        {
                            "user_inapp": ids["user_inapp"],
                            "user_wechat": ids["user_wechat"],
                        },
                    )
                    await session.execute(
                        text(
                            "DELETE FROM wechat_subscription_grants "
                            "WHERE user_id = :user_id AND template_id = :template_id"
                        ),
                        {"user_id": ids["user_wechat"], "template_id": template_id},
                    )
                    await session.execute(
                        text(
                            "DELETE FROM notification_preferences "
                            "WHERE user_id IN (:user_inapp, :user_wechat)"
                        ),
                        {
                            "user_inapp": ids["user_inapp"],
                            "user_wechat": ids["user_wechat"],
                        },
                    )
                    await session.execute(
                        text(
                            "DELETE FROM follows "
                            "WHERE user_id IN (:user_inapp, :user_wechat)"
                        ),
                        {
                            "user_inapp": ids["user_inapp"],
                            "user_wechat": ids["user_wechat"],
                        },
                    )
                if "event" in ids:
                    await session.execute(
                        text("DELETE FROM live_events WHERE id = :event_id"),
                        {"event_id": ids["event"]},
                    )
                if "session" in ids:
                    await session.execute(
                        text("DELETE FROM live_sessions WHERE id = :session_id"),
                        {"session_id": ids["session"]},
                    )
                if "account" in ids:
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
                for key in ("user_inapp", "user_wechat"):
                    if key in ids:
                        await session.execute(
                            text("DELETE FROM users WHERE id = :user_id"),
                            {"user_id": ids[key]},
                        )
                await session.commit()
                remaining = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM users "
                            "WHERE openid IN (:openid_inapp, :openid_wechat)"
                        ),
                        {"openid_inapp": openids[0], "openid_wechat": openids[1]},
                    )
                ).scalar_one()
                cleanup_complete = remaining == 0

    checks["cleanup_complete"] = cleanup_complete
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        json.dumps(
            {
                "gate": "3.5",
                "probe": "postgresql_restart_fallback_notification_e2e",
                "status": status,
                "migration_head": migration_head,
                "checks": checks,
                "provider_called": False,
                "notification_exactly_once_claimed": False,
                "worker_exactly_once_claimed": False,
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
