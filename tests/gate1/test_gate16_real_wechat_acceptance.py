from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)
from stage_letter.application.ports import GrantRepository
from stage_letter.application.services.wechat_delivery import WeChatRetryPolicy
from stage_letter.application.services.wechat_finalize import (
    WeChatAtomicDeliveryAttemptApplicationService,
    WeChatDeliveryFinalizationApplicationService,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    WeChatGrantLedger,
    claim_delivery,
)
from stage_letter.infrastructure.db.repositories.grant import SQLAlchemyGrantRepository


ROOT = Path(__file__).resolve().parents[2]
FINALIZER_PATH = ROOT / "stage_letter" / "application" / "services" / "wechat_finalize.py"
GRANT_REPO_PATH = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories" / "grant.py"
PG_PROBE_PATH = ROOT / "scripts" / "gate16_atomic_finalize_restart_probe.py"
REAL_PROBE_PATH = ROOT / "scripts" / "gate16_real_wechat_acceptance.py"
T0 = datetime(2026, 8, 20, 2, 10, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 20, 2, 11, tzinfo=timezone.utc)


def _claimed(*, attempt: int = 1) -> NotificationDelivery:
    pending = NotificationDelivery(
        key=DeliveryKey("201", "event-401", DeliveryChannel.WECHAT_SUBSCRIBE),
        account_id="101",
        session_id="301",
        created_at=T0,
    )
    if attempt == 1:
        return claim_delivery(pending, now=T0)
    return NotificationDelivery(
        key=pending.key,
        account_id=pending.account_id,
        session_id=pending.session_id,
        created_at=pending.created_at,
        state=DeliveryState.IN_FLIGHT,
        attempt=attempt,
        in_flight_at=T0,
    )


def _outcome(
    kind: ProviderOutcomeKind,
    effect: GrantEffect,
    code: str,
) -> ProviderOutcome:
    return ProviderOutcome(kind, effect, provider_code=code, provider_message="detail")


class _Notifications:
    def __init__(self, delivery: NotificationDelivery) -> None:
        self.delivery = delivery
        self.save_calls = 0

    async def lock_delivery(self, key):
        return self.delivery if key == self.delivery.key else None

    async def get_delivery(self, key):
        return self.delivery if key == self.delivery.key else None

    async def save_delivery(self, delivery):
        self.delivery = delivery
        self.save_calls += 1


class _Grants:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.ledger = WeChatGrantLedger("201", "tpl", 2, 0)
        self.consume_calls = 0
        self.last_error_code = None

    async def consume_wechat_grant(
        self,
        user_id,
        template_id,
        *,
        sent_at,
        error_code=None,
    ):
        self.consume_calls += 1
        self.last_error_code = error_code
        if self.missing:
            return None
        self.ledger = WeChatGrantLedger(
            user_id,
            template_id,
            self.ledger.granted_count,
            self.ledger.consumed_count + 1,
        )
        return self.ledger


class _Uow:
    def __init__(self, delivery: NotificationDelivery, *, missing_grant: bool = False) -> None:
        self.notifications = _Notifications(delivery)
        self.grants = _Grants(missing=missing_grant)
        self.commit_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        return None


class _Provider:
    def __init__(self, outcome: ProviderOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    async def send(self, message):
        self.calls += 1
        return self.outcome


class Gate16RealWeChatAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_atomically_marks_sent_and_consumes_grant(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0"),
            now=T1,
        )
        self.assertEqual(DeliveryState.SENT, result.delivery.state)
        self.assertTrue(result.grant_consumed)
        self.assertEqual(1, result.grant_ledger.consumed_count)  # type: ignore[union-attr]
        self.assertEqual(1, uow.notifications.save_calls)
        self.assertEqual(1, uow.grants.consume_calls)
        self.assertEqual(1, uow.commit_calls)
        self.assertIsNone(uow.grants.last_error_code)

    async def test_43101_waits_auth_and_consumes_with_provider_code(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.AUTH_REQUIRED, GrantEffect.CONSUME, "43101"),
            now=T1,
        )
        self.assertEqual(DeliveryState.WAITING_AUTH, result.delivery.state)
        self.assertEqual(1, uow.grants.consume_calls)
        self.assertEqual("43101", uow.grants.last_error_code)
        self.assertEqual(1, uow.commit_calls)

    async def test_config_blocked_preserves_grant(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.CONFIG_BLOCKED, GrantEffect.PRESERVE, "40037"),
            now=T1,
        )
        self.assertEqual(DeliveryState.BLOCKED_CONFIG, result.delivery.state)
        self.assertFalse(result.grant_consumed)
        self.assertEqual(0, uow.grants.consume_calls)
        self.assertEqual(1, uow.commit_calls)

    async def test_retryable_preserves_grant_and_schedules_retry(self) -> None:
        claimed = _claimed(attempt=2)
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(
            lambda: uow,  # type: ignore[arg-type]
            retry_policy=WeChatRetryPolicy(base_seconds=10, max_seconds=300, max_attempts=8),
        )
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.RETRYABLE, GrantEffect.PRESERVE, "45009"),
            now=T1,
        )
        self.assertEqual(DeliveryState.WAITING_RETRY, result.delivery.state)
        self.assertEqual(0, uow.grants.consume_calls)
        self.assertEqual(T1.timestamp() + 20, result.delivery.next_attempt_at.timestamp())  # type: ignore[union-attr]

    async def test_ambiguous_preserves_grant_and_is_not_blind_retryable(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.AMBIGUOUS, GrantEffect.PRESERVE, "49999"),
            now=T1,
        )
        self.assertEqual(DeliveryState.AMBIGUOUS, result.delivery.state)
        self.assertFalse(result.delivery.allows_blind_retry)
        self.assertEqual(0, uow.grants.consume_calls)

    async def test_retry_exhaustion_is_terminal_without_grant_consumption(self) -> None:
        claimed = _claimed(attempt=8)
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        result = await service.finalize(
            claimed,
            template_id="tpl",
            outcome=_outcome(ProviderOutcomeKind.RETRYABLE, GrantEffect.PRESERVE, "45009"),
            now=T1,
        )
        self.assertEqual(DeliveryState.FAILED_TERMINAL, result.delivery.state)
        self.assertTrue(result.delivery.is_terminal)
        self.assertEqual(0, uow.grants.consume_calls)

    async def test_duplicate_finalize_rejected_before_second_consumption(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        outcome = _outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0")
        await service.finalize(claimed, template_id="tpl", outcome=outcome, now=T1)
        with self.assertRaises(ApplicationInvariantError):
            await service.finalize(claimed, template_id="tpl", outcome=outcome, now=T1)
        self.assertEqual(1, uow.grants.consume_calls)
        self.assertEqual(1, uow.commit_calls)

    async def test_missing_ledger_refuses_fake_sent_commit(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed, missing_grant=True)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.finalize(
                claimed,
                template_id="tpl",
                outcome=_outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0"),
                now=T1,
            )
        self.assertEqual(0, uow.notifications.save_calls)
        self.assertEqual(0, uow.commit_calls)

    async def test_inconsistent_grant_effect_is_invariant_failure(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        service = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.finalize(
                claimed,
                template_id="tpl",
                outcome=_outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.PRESERVE, "0"),
                now=T1,
            )
        self.assertEqual(0, uow.grants.consume_calls)
        self.assertEqual(0, uow.commit_calls)

    async def test_runtime_calls_provider_once_then_atomic_finalizer(self) -> None:
        claimed = _claimed()
        uow = _Uow(claimed)
        finalizer = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        provider = _Provider(_outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0"))
        runtime = WeChatAtomicDeliveryAttemptApplicationService(provider, finalizer)  # type: ignore[arg-type]
        message = WeChatLiveStartMessage(
            openid="openid",
            template_id="tpl",
            anchor_name="主播",
            room_title="开播",
            start_time="2026-08-20 10:00",
        )
        result = await runtime.execute(claimed, message, now=T1)
        self.assertEqual(1, provider.calls)
        self.assertEqual(DeliveryState.SENT, result.delivery.state)
        self.assertEqual(1, uow.commit_calls)

    async def test_runtime_rejects_non_inflight_before_provider_call(self) -> None:
        pending = NotificationDelivery(
            DeliveryKey("201", "event-401", DeliveryChannel.WECHAT_SUBSCRIBE),
            "101",
            "301",
            T0,
        )
        uow = _Uow(pending)
        finalizer = WeChatDeliveryFinalizationApplicationService(lambda: uow)  # type: ignore[arg-type]
        provider = _Provider(_outcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0"))
        runtime = WeChatAtomicDeliveryAttemptApplicationService(provider, finalizer)  # type: ignore[arg-type]
        message = WeChatLiveStartMessage("openid", "tpl", "主播", "开播", "2026-08-20 10:00")
        with self.assertRaises(ApplicationInvariantError):
            await runtime.execute(pending, message, now=T1)
        self.assertEqual(0, provider.calls)

    def test_grant_repository_structurally_implements_extended_port(self) -> None:
        self.assertIsInstance(SQLAlchemyGrantRepository(object()), GrantRepository)  # type: ignore[arg-type]
        self.assertIn("consume_wechat_grant", dir(SQLAlchemyGrantRepository))

    def test_grant_consumption_uses_row_lock_and_allows_ledger_drift(self) -> None:
        source = inspect.getsource(SQLAlchemyGrantRepository.consume_wechat_grant)
        self.assertIn("with_for_update()", source)
        self.assertIn("consumed_count", source)
        self.assertNotIn("granted_count >", source)
        self.assertNotIn("consumed_count <", source)

    def test_finalizer_application_layer_has_no_infrastructure_or_network_dependency(self) -> None:
        tree = ast.parse(FINALIZER_PATH.read_text(encoding="utf-8"), filename=str(FINALIZER_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "httpx",
            "requests",
        )
        violations = []
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)

    def test_postgres_probe_freezes_atomic_restart_and_no_provider_claims(self) -> None:
        source = PG_PROBE_PATH.read_text(encoding="utf-8")
        for required in (
            'EXPECTED_HEAD = "a63f4b2d9e71"',
            '"duplicate_finalize_rejected"',
            '"restart_preserved_sent"',
            '"crash_recovered_ambiguous"',
            '"crash_did_not_consume_grant"',
            '"real_wechat_called": False',
            '"provider_exactly_once_claimed": False',
            '"notification_exactly_once_claimed": False',
        ):
            self.assertIn(required, source)

    def test_real_probe_requires_explicit_send_and_never_mutates_live_truth(self) -> None:
        source = REAL_PROBE_PATH.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--send"', source)
        self.assertIn('"status": "ARMED"', source)
        self.assertIn('"real_wechat_called": True', source)
        self.assertIn('"production_approved": passed', source)
        self.assertNotIn("INSERT INTO live_events", source)
        self.assertNotIn("UPDATE live_events", source)
        self.assertNotIn("INSERT INTO live_sessions", source)
        self.assertNotIn("UPDATE live_sessions", source)
        self.assertNotIn("INSERT INTO live_observations", source)
        self.assertNotIn("UPDATE live_observations", source)


if __name__ == "__main__":
    unittest.main()
