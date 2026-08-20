from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.services.notification_delivery import (
    NotificationDeliveryApplicationService,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    recover_delivery_as_ambiguous,
    schedule_delivery_retry,
)
from stage_letter.infrastructure.db.models import NotificationDeliveryModel
from stage_letter.infrastructure.db.repositories.notification import (
    SQLAlchemyNotificationRepository,
)


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "notification_delivery.py"
MIGRATION_PATH = ROOT / "migrations" / "versions" / "a63f4b2d9e71_gate16_delivery_execution_indexes.py"
T0 = datetime(2026, 8, 20, 1, 30, tzinfo=timezone.utc)


def _key(user_id: str = "201") -> DeliveryKey:
    return DeliveryKey(
        user_id=user_id,
        live_event_id="live-event:gate16-3",
        channel=DeliveryChannel.WECHAT_SUBSCRIBE,
    )


def _pending(user_id: str = "201") -> NotificationDelivery:
    return NotificationDelivery(
        key=_key(user_id),
        account_id="101",
        session_id="501",
        created_at=T0 - timedelta(minutes=5),
    )


def _in_flight(user_id: str = "201", *, at: datetime = T0) -> NotificationDelivery:
    return claim_delivery(_pending(user_id), now=at)


class _FakeUoW:
    def __init__(self) -> None:
        self.notifications = SimpleNamespace(
            list_due_delivery_keys=AsyncMock(return_value=()),
            list_stale_in_flight_keys=AsyncMock(return_value=()),
            lock_delivery=AsyncMock(return_value=None),
            get_delivery=AsyncMock(return_value=None),
            save_delivery=AsyncMock(),
        )
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class Gate16DeliveryStateMachineTests(unittest.IsolatedAsyncioTestCase):
    def test_pending_claim_enters_in_flight_attempt_one(self) -> None:
        claimed = claim_delivery(_pending(), now=T0)
        self.assertEqual(DeliveryState.IN_FLIGHT, claimed.state)
        self.assertEqual(1, claimed.attempt)
        self.assertEqual(T0, claimed.in_flight_at)
        self.assertIsNone(claimed.next_attempt_at)
        self.assertFalse(claimed.allows_blind_retry)

    def test_in_flight_can_schedule_explicit_retry(self) -> None:
        delivery = _in_flight()
        retry = schedule_delivery_retry(
            delivery,
            now=T0 + timedelta(seconds=5),
            delay_seconds=30,
            error_code="TEMPORARY",
        )
        self.assertEqual(DeliveryState.WAITING_RETRY, retry.state)
        self.assertEqual(T0 + timedelta(seconds=35), retry.next_attempt_at)
        self.assertIsNone(retry.in_flight_at)
        self.assertEqual("TEMPORARY", retry.error_code)
        self.assertTrue(retry.allows_blind_retry)

    def test_retry_cannot_claim_before_due(self) -> None:
        retry = schedule_delivery_retry(
            _in_flight(),
            now=T0,
            delay_seconds=30,
        )
        with self.assertRaises(ValueError):
            claim_delivery(retry, now=T0 + timedelta(seconds=29))

    def test_due_retry_claim_increments_attempt(self) -> None:
        retry = schedule_delivery_retry(
            _in_flight(),
            now=T0,
            delay_seconds=30,
            error_code="OLD",
        )
        claimed = claim_delivery(retry, now=T0 + timedelta(seconds=30))
        self.assertEqual(DeliveryState.IN_FLIGHT, claimed.state)
        self.assertEqual(2, claimed.attempt)
        self.assertIsNone(claimed.error_code)
        self.assertEqual(T0 + timedelta(seconds=30), claimed.in_flight_at)

    def test_sent_is_terminal(self) -> None:
        sent = mark_delivery_sent(_in_flight(), now=T0 + timedelta(seconds=1))
        self.assertEqual(DeliveryState.SENT, sent.state)
        self.assertTrue(sent.is_terminal)
        self.assertFalse(sent.allows_blind_retry)
        self.assertEqual(T0 + timedelta(seconds=1), sent.sent_at)
        with self.assertRaises(ValueError):
            claim_delivery(sent, now=T0 + timedelta(minutes=1))

    def test_waiting_auth_is_not_blind_retryable(self) -> None:
        delivery = mark_delivery_waiting_auth(
            _in_flight(),
            now=T0,
            error_code="AUTH_REQUIRED",
        )
        self.assertEqual(DeliveryState.WAITING_AUTH, delivery.state)
        self.assertFalse(delivery.allows_blind_retry)
        with self.assertRaises(ValueError):
            claim_delivery(delivery, now=T0 + timedelta(minutes=1))

    def test_blocked_config_is_not_blind_retryable(self) -> None:
        delivery = mark_delivery_blocked_config(
            _in_flight(),
            now=T0,
            error_code="CONFIG_BLOCKED",
        )
        self.assertEqual(DeliveryState.BLOCKED_CONFIG, delivery.state)
        self.assertFalse(delivery.allows_blind_retry)

    def test_failed_terminal_is_terminal(self) -> None:
        delivery = mark_delivery_failed_terminal(
            _in_flight(),
            now=T0,
            error_code="TERMINAL",
        )
        self.assertEqual(DeliveryState.FAILED_TERMINAL, delivery.state)
        self.assertTrue(delivery.is_terminal)
        self.assertFalse(delivery.allows_blind_retry)

    def test_crash_recovery_becomes_ambiguous_without_blind_retry(self) -> None:
        inflight = _in_flight(at=T0 - timedelta(minutes=2))
        recovered = recover_delivery_as_ambiguous(inflight, now=T0)
        self.assertEqual(DeliveryState.AMBIGUOUS, recovered.state)
        self.assertEqual(inflight.in_flight_at, recovered.in_flight_at)
        self.assertEqual("CRASH_RECOVERY_AMBIGUOUS", recovered.error_code)
        self.assertFalse(recovered.allows_blind_retry)
        with self.assertRaises(ValueError):
            claim_delivery(recovered, now=T0 + timedelta(minutes=1))

    def test_pending_execution_metadata_is_strict(self) -> None:
        with self.assertRaises(ValueError):
            NotificationDelivery(
                key=_key(),
                account_id="101",
                session_id="501",
                created_at=T0,
                state=DeliveryState.PENDING,
                attempt=1,
            )
        with self.assertRaises(ValueError):
            NotificationDelivery(
                key=_key(),
                account_id="101",
                session_id="501",
                created_at=T0,
                state=DeliveryState.IN_FLIGHT,
                attempt=1,
            )

    async def test_service_claim_next_due_persists_inflight_and_commits(self) -> None:
        uow = _FakeUoW()
        uow.notifications.list_due_delivery_keys.return_value = (_key(),)
        uow.notifications.lock_delivery.return_value = _pending()
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        claimed = await service.claim_next_due(now=T0)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(DeliveryState.IN_FLIGHT, claimed.state)
        uow.notifications.save_delivery.assert_awaited_once_with(claimed)
        uow.commit.assert_awaited_once()

    async def test_service_claim_skips_locked_candidate_and_claims_next(self) -> None:
        uow = _FakeUoW()
        first = _key("201")
        second = _key("202")
        uow.notifications.list_due_delivery_keys.return_value = (first, second)
        uow.notifications.lock_delivery.side_effect = [None, _pending("202")]
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        claimed = await service.claim_next_due(now=T0)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual("202", claimed.key.user_id)
        self.assertEqual(2, uow.notifications.lock_delivery.await_count)
        uow.commit.assert_awaited_once()

    async def test_service_schedule_retry_rejects_non_inflight(self) -> None:
        uow = _FakeUoW()
        uow.notifications.lock_delivery.return_value = _pending()
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        with self.assertRaises(ApplicationInvariantError):
            await service.schedule_retry(
                _key(),
                now=T0,
                delay_seconds=10,
            )

        uow.notifications.save_delivery.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_service_recovery_marks_stale_inflight_ambiguous(self) -> None:
        uow = _FakeUoW()
        stale = _in_flight(at=T0 - timedelta(minutes=2))
        uow.notifications.list_stale_in_flight_keys.return_value = (stale.key,)
        uow.notifications.lock_delivery.return_value = stale
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.recover_stale_in_flight(
            now=T0,
            stale_after_seconds=60,
        )

        self.assertEqual(1, result.examined)
        self.assertEqual(1, result.recovered_ambiguous)
        saved = uow.notifications.save_delivery.await_args.args[0]
        self.assertEqual(DeliveryState.AMBIGUOUS, saved.state)
        uow.commit.assert_awaited_once()

    async def test_service_recovery_noop_does_not_commit(self) -> None:
        uow = _FakeUoW()
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.recover_stale_in_flight(
            now=T0,
            stale_after_seconds=60,
        )

        self.assertEqual(0, result.examined)
        self.assertEqual(0, result.recovered_ambiguous)
        uow.commit.assert_not_awaited()

    def test_migration_and_model_declare_due_and_inflight_indexes(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision: str = "a63f4b2d9e71"', source)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "f16e2a7c4d10"', source)
        self.assertIn('DUE_INDEX = "idx_g163_delivery_due"', source)
        self.assertIn('IN_FLIGHT_INDEX = "idx_g163_delivery_inflight"', source)
        self.assertNotIn("UPDATE notification_deliveries", source)

        indexes = {index.name: index for index in NotificationDeliveryModel.__table__.indexes}
        self.assertEqual(
            ("state", "next_attempt_at", "id"),
            tuple(column.name for column in indexes["idx_g163_delivery_due"].columns),
        )
        self.assertEqual(
            ("state", "in_flight_at", "id"),
            tuple(column.name for column in indexes["idx_g163_delivery_inflight"].columns),
        )

    def test_repository_persists_execution_metadata_and_uses_skip_locked_claiming(self) -> None:
        save_source = inspect.getsource(SQLAlchemyNotificationRepository.save_delivery)
        for field in (
            "row.state",
            "row.attempt",
            "row.next_attempt_at",
            "row.in_flight_at",
            "row.sent_at",
            "row.error_code",
            "row.error_message",
        ):
            self.assertIn(field, save_source)

        lock_source = inspect.getsource(SQLAlchemyNotificationRepository.lock_delivery)
        self.assertIn("with_for_update(skip_locked=True)", lock_source)
        due_source = inspect.getsource(SQLAlchemyNotificationRepository.list_due_delivery_keys)
        self.assertIn("DeliveryState.PENDING", due_source)
        self.assertIn("DeliveryState.WAITING_RETRY", due_source)
        stale_source = inspect.getsource(SQLAlchemyNotificationRepository.list_stale_in_flight_keys)
        self.assertIn("DeliveryState.IN_FLIGHT", stale_source)
        self.assertIn("in_flight_at <= stale_before", stale_source)

    def test_delivery_service_has_no_provider_network_or_live_truth_mutation_dependency(self) -> None:
        tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"), filename=str(SERVICE_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "workers",
            "api",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "requests",
            "httpx",
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
        self.assertNotIn("send_subscribe", source)
        self.assertNotIn("save_session", source)
        self.assertNotIn("append_event", source)


if __name__ == "__main__":
    unittest.main()
