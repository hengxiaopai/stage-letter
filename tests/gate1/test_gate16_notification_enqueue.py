from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from stage_letter.application.errors import ApplicationNotFoundError
from stage_letter.application.services.follow import FollowApplicationService
from stage_letter.application.services.notification_enqueue import (
    NotificationEnqueueApplicationService,
)
from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import LiveEvent, LiveEventCause, LiveEventType
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryState,
    GrantState,
    WeChatGrantLedger,
    resolve_wechat_grant_state,
)
from stage_letter.infrastructure.db.base import Base


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "notification_enqueue.py"
MIGRATION_PATH = ROOT / "migrations" / "versions" / "f16e2a7c4d10_gate16_recipient_resolution.py"
GRANT_REPO_PATH = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories" / "grant.py"
T0 = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)


def _event(
    *,
    event_type: LiveEventType = LiveEventType.LIVE_STARTED,
    cause: LiveEventCause = LiveEventCause.TRANSITION,
) -> LiveEvent:
    return LiveEvent(
        event_id="live-event:gate16-2",
        account_id="101",
        session_id="501",
        event_type=event_type,
        cause=cause,
        occurred_at=T0,
    )


def _follow(user_id: str = "201") -> Follow:
    return Follow(user_id=user_id, creator_id="301", account_id="101")


def _preference(user_id: str = "201", *, enabled: bool = True) -> NotificationPreference:
    return NotificationPreference(user_id=user_id, account_id="101", enabled=enabled)


def _grant(user_id: str = "201", *, granted: int = 2, consumed: int = 0) -> WeChatGrantLedger:
    return WeChatGrantLedger(
        user_id=user_id,
        template_id="tpl-live-start",
        granted_count=granted,
        consumed_count=consumed,
    )


class _FakeUoW:
    def __init__(self) -> None:
        self.creators = SimpleNamespace(get_account=AsyncMock(return_value=None))
        self.follows = SimpleNamespace(
            list_follows_for_account=AsyncMock(return_value=()),
            get_notification_preference=AsyncMock(return_value=None),
            save_follow=AsyncMock(),
            save_notification_preference=AsyncMock(),
        )
        self.live = SimpleNamespace(get_event=AsyncMock(return_value=_event()))
        self.notifications = SimpleNamespace(create_delivery=AsyncMock(return_value=True))
        self.grants = SimpleNamespace(get_wechat_grant=AsyncMock(return_value=None))
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class Gate16NotificationEnqueueTests(unittest.IsolatedAsyncioTestCase):
    def test_positive_grant_balance_resolves_granted(self) -> None:
        ledger = _grant(granted=3, consumed=1)
        self.assertEqual(2, ledger.available)
        self.assertEqual(GrantState.GRANTED, resolve_wechat_grant_state(ledger))

    def test_missing_zero_or_overconsumed_grant_resolves_exhausted(self) -> None:
        self.assertEqual(GrantState.EXHAUSTED, resolve_wechat_grant_state(None))
        self.assertEqual(
            GrantState.EXHAUSTED,
            resolve_wechat_grant_state(_grant(granted=1, consumed=1)),
        )
        over = _grant(granted=1, consumed=2)
        self.assertEqual(0, over.available)
        self.assertEqual(GrantState.EXHAUSTED, resolve_wechat_grant_state(over))

    async def test_follow_preserves_existing_disabled_preference(self) -> None:
        uow = _FakeUoW()
        uow.creators.get_account.return_value = PlatformAccount("101", "301", "douyin", "dy-301")
        uow.follows.get_notification_preference.return_value = _preference(enabled=False)
        service = FollowApplicationService(lambda: uow)  # type: ignore[arg-type]

        await service.follow_account(user_id="201", account_id="101")

        uow.follows.save_follow.assert_awaited_once()
        uow.follows.save_notification_preference.assert_not_awaited()
        uow.commit.assert_awaited_once()

    async def test_missing_event_fails_without_enqueue_or_commit(self) -> None:
        uow = _FakeUoW()
        uow.live.get_event.return_value = None
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        with self.assertRaises(ApplicationNotFoundError):
            await service.enqueue_live_event(event_id="missing", template_id="tpl-live-start")

        uow.notifications.create_delivery.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_recipient_query_is_event_time_bounded(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = ()
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(0, result.examined)
        uow.follows.list_follows_for_account.assert_awaited_once_with(
            "101",
            created_at_lte=T0,
            after_user_id=None,
            limit=500,
        )

    async def test_missing_preference_is_skipped_without_grant_lookup(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = None
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(1, result.skipped_missing_preference)
        uow.grants.get_wechat_grant.assert_not_awaited()
        uow.notifications.create_delivery.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_disabled_preference_is_ineligible(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = _preference(enabled=False)
        uow.grants.get_wechat_grant.return_value = _grant()
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(1, result.skipped_ineligible)
        uow.notifications.create_delivery.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_missing_grant_is_ineligible(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = _preference()
        uow.grants.get_wechat_grant.return_value = None
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(1, result.skipped_ineligible)
        uow.notifications.create_delivery.assert_not_awaited()

    async def test_exhausted_grant_is_ineligible(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = _preference()
        uow.grants.get_wechat_grant.return_value = _grant(granted=1, consumed=1)
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(1, result.skipped_ineligible)
        uow.notifications.create_delivery.assert_not_awaited()

    async def test_eligible_target_creates_pending_delivery_and_commits(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = _preference()
        uow.grants.get_wechat_grant.return_value = _grant()
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(1, result.created)
        self.assertEqual(0, result.reused_existing)
        delivery = uow.notifications.create_delivery.await_args.args[0]
        self.assertEqual("201", delivery.key.user_id)
        self.assertEqual("live-event:gate16-2", delivery.key.live_event_id)
        self.assertEqual(DeliveryChannel.WECHAT_SUBSCRIBE, delivery.key.channel)
        self.assertEqual(DeliveryState.PENDING, delivery.state)
        uow.commit.assert_awaited_once()

    async def test_duplicate_logical_delivery_is_reused_without_new_commit(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.return_value = (_follow(),)
        uow.follows.get_notification_preference.return_value = _preference()
        uow.grants.get_wechat_grant.return_value = _grant()
        uow.notifications.create_delivery.return_value = False
        service = NotificationEnqueueApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(0, result.created)
        self.assertEqual(1, result.reused_existing)
        uow.commit.assert_not_awaited()

    async def test_recipient_pagination_uses_stable_user_cursor(self) -> None:
        uow = _FakeUoW()
        uow.follows.list_follows_for_account.side_effect = [
            (_follow("201"),),
            (_follow("202"),),
            (),
        ]
        uow.follows.get_notification_preference.side_effect = [
            _preference("201"),
            _preference("202"),
        ]
        uow.grants.get_wechat_grant.side_effect = [
            _grant("201"),
            _grant("202"),
        ]
        service = NotificationEnqueueApplicationService(
            lambda: uow,  # type: ignore[arg-type]
            batch_size=1,
        )

        result = await service.enqueue_live_event(
            event_id="live-event:gate16-2",
            template_id="tpl-live-start",
        )

        self.assertEqual(2, result.examined)
        self.assertEqual(2, result.created)
        self.assertEqual(
            [
                call("101", created_at_lte=T0, after_user_id=None, limit=1),
                call("101", created_at_lte=T0, after_user_id="201", limit=1),
                call("101", created_at_lte=T0, after_user_id="202", limit=1),
            ],
            uow.follows.list_follows_for_account.await_args_list,
        )
        uow.commit.assert_awaited_once()

    def test_enqueue_service_has_no_provider_network_or_live_mutation_dependency(self) -> None:
        tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"), filename=str(SERVICE_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "workers",
            "api",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "httpx",
            "requests",
        )
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)

        source = SERVICE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("access_token", source)
        self.assertNotIn("save_session", source)
        self.assertNotIn("append_event", source)
        self.assertNotIn("send_wechat", source)

    def test_gate16_migration_extends_gate14_and_only_repairs_recipient_contract(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision: str = "f16e2a7c4d10"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "d14e7c9a5b30"', source)
        self.assertIn('INDEX_NAME = "idx_g16_follows_account_user"', source)
        self.assertIn("INSERT INTO notification_preferences", source)
        self.assertIn("TRUE", source)
        self.assertNotIn("CREATE TABLE wechat_subscription_grants", source)
        self.assertNotIn("op.drop_table", source)

    def test_grant_mapping_does_not_expand_frozen_formal_domain_metadata(self) -> None:
        self.assertNotIn("wechat_subscription_grants", Base.metadata.tables)
        source = GRANT_REPO_PATH.read_text(encoding="utf-8")
        self.assertIn("MetaData()", source)
        self.assertIn('Table(\n    "wechat_subscription_grants"', source)
        self.assertNotIn("from stage_letter.infrastructure.db.base import Base", source)


if __name__ == "__main__":
    unittest.main()
