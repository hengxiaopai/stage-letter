from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from stage_letter.application.notification_providers import ProviderOutcomeKind, WeChatLiveStartMessage
from stage_letter.application.services.notification_delivery import NotificationDeliveryApplicationService
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
)
from stage_letter.infrastructure.notifications.wechat import (
    WeChatSendAmbiguousError,
    WeChatSubscribeFormalAdapter,
    WeChatTokenUnavailableError,
)

T0 = datetime(2026, 8, 20, 2, 40, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 20, 2, 41, tzinfo=timezone.utc)


def _claimed() -> NotificationDelivery:
    pending = NotificationDelivery(
        key=DeliveryKey("201", "event-provider-integration", DeliveryChannel.WECHAT_SUBSCRIBE),
        account_id="101",
        session_id="301",
        created_at=T0,
    )
    return claim_delivery(pending, now=T0)


def _message() -> WeChatLiveStartMessage:
    return WeChatLiveStartMessage(
        openid="probe-openid",
        template_id="probe-template",
        anchor_name="Probe",
        room_title="Room",
        start_time="2026-08-20 10:40",
    )


class _UoW:
    def __init__(self, delivery: NotificationDelivery) -> None:
        self.notifications = SimpleNamespace(
            lock_delivery=AsyncMock(return_value=delivery),
            get_delivery=AsyncMock(return_value=delivery),
            save_delivery=AsyncMock(),
        )
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SecretErrorGateway:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def send(self, message, data):
        raise self.exc


class Gate16WeChatProviderStateIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_delivery_service_persists_provider_ambiguous(self) -> None:
        claimed = _claimed()
        uow = _UoW(claimed)
        service = NotificationDeliveryApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.mark_ambiguous(
            claimed.key,
            now=T1,
            error_code="SEND_TRANSPORT_AMBIGUOUS",
            error_message="wechat send outcome ambiguous",
        )

        self.assertEqual(DeliveryState.AMBIGUOUS, result.state)
        self.assertEqual(T0, result.in_flight_at)
        self.assertFalse(result.allows_blind_retry)
        uow.notifications.save_delivery.assert_awaited_once_with(result)
        uow.commit.assert_awaited_once()

    async def test_transport_exception_text_is_never_exposed(self) -> None:
        secret = "DO-NOT-LEAK-SECRET-TOKEN"
        cases = (
            (
                WeChatTokenUnavailableError(secret),
                ProviderOutcomeKind.RETRYABLE,
                "wechat token unavailable",
            ),
            (
                WeChatSendAmbiguousError(secret),
                ProviderOutcomeKind.AMBIGUOUS,
                "wechat send outcome ambiguous",
            ),
        )
        for exc, expected_kind, expected_message in cases:
            with self.subTest(exc=type(exc).__name__):
                adapter = WeChatSubscribeFormalAdapter(_SecretErrorGateway(exc))
                outcome = await adapter.send(_message())
                self.assertEqual(expected_kind, outcome.kind)
                self.assertEqual(expected_message, outcome.provider_message)
                self.assertNotIn(secret, outcome.provider_message or "")


if __name__ == "__main__":
    unittest.main()
