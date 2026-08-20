from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
)
from workers.notification_runtime import WeChatNotificationRuntime


ROOT = Path(__file__).resolve().parents[2]
OLD_COMPOSITION = ROOT / "workers" / "composition.py"
NEW_COMPOSITION = ROOT / "workers" / "notification_composition.py"
REAL_PROBE = ROOT / "scripts" / "gate16_real_wechat_acceptance.py"
T0 = datetime(2026, 8, 20, 2, 30, tzinfo=timezone.utc)


def _claimed() -> NotificationDelivery:
    pending = NotificationDelivery(
        DeliveryKey("201", "event-401", DeliveryChannel.WECHAT_SUBSCRIBE),
        "101",
        "301",
        T0,
    )
    return claim_delivery(pending, now=T0)


class _Provider:
    async def send(self, message):
        return ProviderOutcome(
            ProviderOutcomeKind.ACCEPTED,
            GrantEffect.CONSUME,
            "0",
            "ok",
        )


class _DummySessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalar(self, statement):
        return "openid"


class _DummyUoW:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class Gate16NotificationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self) -> WeChatNotificationRuntime:
        return WeChatNotificationRuntime(
            uow_factory=lambda: _DummyUoW(),  # type: ignore[arg-type]
            session_factory=_DummySessionFactory(),  # type: ignore[arg-type]
            provider=_Provider(),
            template_id="tpl",
        )

    async def test_run_once_idle_does_not_build_message_or_call_provider(self) -> None:
        runtime = self._runtime()
        runtime._delivery_service = SimpleNamespace(
            claim_next_due=AsyncMock(return_value=None),
        )
        runtime._get_openid = AsyncMock(side_effect=AssertionError("openid must not resolve"))  # type: ignore[method-assign]
        result = await runtime.run_once(now=T0)
        self.assertEqual("IDLE", result.action)
        self.assertIsNone(result.delivery)

    async def test_missing_openid_moves_claimed_delivery_to_waiting_auth(self) -> None:
        runtime = self._runtime()
        claimed = _claimed()
        waiting = NotificationDelivery(
            claimed.key,
            claimed.account_id,
            claimed.session_id,
            claimed.created_at,
            state=DeliveryState.WAITING_AUTH,
            attempt=claimed.attempt,
            error_code="OPENID_MISSING",
        )
        runtime._delivery_service = SimpleNamespace(
            claim_next_due=AsyncMock(return_value=claimed),
            mark_waiting_auth=AsyncMock(return_value=waiting),
        )
        runtime._get_openid = AsyncMock(return_value=None)  # type: ignore[method-assign]
        result = await runtime.run_once(now=T0)
        self.assertEqual("WAITING_AUTH", result.action)
        self.assertEqual(DeliveryState.WAITING_AUTH, result.delivery.state)  # type: ignore[union-attr]

    async def test_invalid_context_becomes_failed_terminal_without_provider(self) -> None:
        runtime = self._runtime()
        claimed = _claimed()
        failed = NotificationDelivery(
            claimed.key,
            claimed.account_id,
            claimed.session_id,
            claimed.created_at,
            state=DeliveryState.FAILED_TERMINAL,
            attempt=claimed.attempt,
            error_code="DELIVERY_CONTEXT_INVALID",
        )
        runtime._delivery_service = SimpleNamespace(
            claim_next_due=AsyncMock(return_value=claimed),
            mark_failed_terminal=AsyncMock(return_value=failed),
        )
        runtime._get_openid = AsyncMock(return_value="openid")  # type: ignore[method-assign]
        runtime._build_message = AsyncMock(return_value=None)  # type: ignore[method-assign]
        runtime._attempt_service = SimpleNamespace(
            execute=AsyncMock(side_effect=AssertionError("provider must not run"))
        )
        result = await runtime.run_once(now=T0)
        self.assertEqual("FAILED_TERMINAL", result.action)
        self.assertEqual(DeliveryState.FAILED_TERMINAL, result.delivery.state)  # type: ignore[union-attr]

    async def test_valid_context_delegates_exactly_one_atomic_attempt(self) -> None:
        runtime = self._runtime()
        claimed = _claimed()
        sent = NotificationDelivery(
            claimed.key,
            claimed.account_id,
            claimed.session_id,
            claimed.created_at,
            state=DeliveryState.SENT,
            attempt=claimed.attempt,
            sent_at=T0,
        )
        message = WeChatLiveStartMessage("openid", "tpl", "主播", "直播间", "2026-08-20 10:30")
        final = SimpleNamespace(
            delivery=sent,
            provider_outcome=ProviderOutcome(
                ProviderOutcomeKind.ACCEPTED,
                GrantEffect.CONSUME,
                "0",
                "ok",
            ),
            grant_consumed=True,
        )
        attempt = AsyncMock(return_value=final)
        runtime._delivery_service = SimpleNamespace(
            claim_next_due=AsyncMock(return_value=claimed),
        )
        runtime._get_openid = AsyncMock(return_value="openid")  # type: ignore[method-assign]
        runtime._build_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
        runtime._attempt_service = SimpleNamespace(execute=attempt)
        result = await runtime.run_once(now=T0)
        attempt.assert_awaited_once_with(claimed, message, now=T0)
        self.assertEqual("SENT", result.action)
        self.assertTrue(result.grant_consumed)

    async def test_restart_recovery_delegates_to_delivery_state_machine(self) -> None:
        runtime = self._runtime()
        recovery = SimpleNamespace(examined=2, recovered_ambiguous=1)
        call = AsyncMock(return_value=recovery)
        runtime._delivery_service = SimpleNamespace(recover_stale_in_flight=call)
        result = await runtime.recover_after_restart(
            now=T0,
            stale_after_seconds=60,
            limit=50,
        )
        self.assertIs(result, recovery)
        call.assert_awaited_once_with(now=T0, stale_after_seconds=60, limit=50)

    def test_notification_composition_is_separate_and_real_preflight_is_read_only(self) -> None:
        old_source = OLD_COMPOSITION.read_text(encoding="utf-8")
        new_source = NEW_COMPOSITION.read_text(encoding="utf-8")
        probe_source = REAL_PROBE.read_text(encoding="utf-8")
        self.assertNotIn("Notification", old_source)
        self.assertIn("build_wechat_notification_runtime", new_source)
        self.assertIn("construction performs no DB or provider request", new_source)
        self.assertLess(
            probe_source.index('if not args.send:'),
            probe_source.index("create_delivery(delivery)"),
        )
        self.assertIn('"database_write_performed": False', probe_source)


if __name__ == "__main__":
    unittest.main()
