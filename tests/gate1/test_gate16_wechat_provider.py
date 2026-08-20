from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)
from stage_letter.application.services.wechat_delivery import (
    WeChatDeliveryAttemptApplicationService,
    WeChatRetryPolicy,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    DeliveryState,
    NotificationDelivery,
    claim_delivery,
    mark_delivery_ambiguous,
    mark_delivery_blocked_config,
    mark_delivery_failed_terminal,
    mark_delivery_sent,
    mark_delivery_waiting_auth,
    schedule_delivery_retry,
)
from stage_letter.infrastructure.notifications.wechat import (
    ERR_RATE_LIMIT,
    ERR_TEMPLATE_INVALID,
    ERR_TOKEN_EXPIRED,
    ERR_TOKEN_INVALID,
    ERR_USER_REFUSE,
    HttpxWeChatProviderGateway,
    WeChatRawResponse,
    WeChatSendAmbiguousError,
    WeChatSubscribeFormalAdapter,
    WeChatTokenUnavailableError,
    build_live_start_template_data,
    normalize_wechat_response,
)


ROOT = Path(__file__).resolve().parents[2]
APP_PROVIDER_PATH = ROOT / "stage_letter" / "application" / "notification_providers.py"
APP_SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "wechat_delivery.py"
INFRA_PATH = ROOT / "stage_letter" / "infrastructure" / "notifications" / "wechat.py"
T0 = datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 20, 2, 1, tzinfo=timezone.utc)


def _message(**overrides) -> WeChatLiveStartMessage:
    values = {
        "openid": "openid-user-201",
        "template_id": "tpl-live-start",
        "anchor_name": "主播名称",
        "room_title": "直播间标题",
        "start_time": "2026-08-20 10:00",
        "theme": "开播啦",
        "activity": "无",
        "page": "pages/creator/detail?id=101",
    }
    values.update(overrides)
    return WeChatLiveStartMessage(**values)


def _pending() -> NotificationDelivery:
    return NotificationDelivery(
        key=DeliveryKey("201", "event-401", DeliveryChannel.WECHAT_SUBSCRIBE),
        account_id="101",
        session_id="301",
        created_at=T0,
    )


def _claimed(*, attempt: int = 1) -> NotificationDelivery:
    if attempt == 1:
        return claim_delivery(_pending(), now=T0)
    return NotificationDelivery(
        key=_pending().key,
        account_id="101",
        session_id="301",
        created_at=T0,
        state=DeliveryState.IN_FLIGHT,
        attempt=attempt,
        in_flight_at=T0,
    )


class _Gateway:
    def __init__(self, raw: WeChatRawResponse | None = None, exc: Exception | None = None) -> None:
        self.raw = raw or WeChatRawResponse(200, {"errcode": 0, "errmsg": "ok"})
        self.exc = exc
        self.calls = 0
        self.last_data = None

    async def send(self, message, data):
        self.calls += 1
        self.last_data = data
        if self.exc is not None:
            raise self.exc
        return self.raw


class _Provider:
    def __init__(self, outcome: ProviderOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    async def send(self, message: WeChatLiveStartMessage) -> ProviderOutcome:
        self.calls += 1
        return self.outcome


class _StateService:
    def __init__(self, delivery: NotificationDelivery) -> None:
        self.delivery = delivery
        self.last_delay = None

    async def mark_sent(self, key, *, now):
        self.delivery = mark_delivery_sent(self.delivery, now=now)
        return self.delivery

    async def mark_waiting_auth(self, key, *, now, error_code=None, error_message=None):
        self.delivery = mark_delivery_waiting_auth(
            self.delivery,
            now=now,
            error_code=error_code,
            error_message=error_message,
        )
        return self.delivery

    async def mark_blocked_config(self, key, *, now, error_code=None, error_message=None):
        self.delivery = mark_delivery_blocked_config(
            self.delivery,
            now=now,
            error_code=error_code,
            error_message=error_message,
        )
        return self.delivery

    async def mark_failed_terminal(self, key, *, now, error_code=None, error_message=None):
        self.delivery = mark_delivery_failed_terminal(
            self.delivery,
            now=now,
            error_code=error_code,
            error_message=error_message,
        )
        return self.delivery

    async def mark_ambiguous(self, key, *, now, error_code=None, error_message=None):
        self.delivery = mark_delivery_ambiguous(
            self.delivery,
            now=now,
            error_code=error_code or "PROVIDER_OUTCOME_AMBIGUOUS",
            error_message=error_message,
        )
        return self.delivery

    async def schedule_retry(
        self,
        key,
        *,
        now,
        delay_seconds,
        error_code=None,
        error_message=None,
    ):
        self.last_delay = delay_seconds
        self.delivery = schedule_delivery_retry(
            self.delivery,
            now=now,
            delay_seconds=delay_seconds,
            error_code=error_code,
            error_message=error_message,
        )
        return self.delivery


class Gate16WeChatProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_message_rejects_blank_required_and_invalid_state(self) -> None:
        for field in ("openid", "template_id", "anchor_name", "room_title", "start_time"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                _message(**{field: " "})
        with self.assertRaises(ValueError):
            _message(miniprogram_state="unknown")
        with self.assertRaises(ValueError):
            _message(page=" ")

    def test_template_data_uses_exact_fields_and_truncates_thing_values(self) -> None:
        message = _message(
            anchor_name="A" * 25,
            room_title="B" * 25,
            theme="C" * 25,
            activity="D" * 25,
        )
        data = build_live_start_template_data(message)
        self.assertEqual({"thing1", "thing2", "time3", "thing5", "thing6"}, set(data))
        self.assertEqual("A" * 20, data["thing1"]["value"])
        self.assertEqual("B" * 20, data["thing2"]["value"])
        self.assertEqual("C" * 20, data["thing5"]["value"])
        self.assertEqual("D" * 20, data["thing6"]["value"])
        self.assertEqual("2026-08-20 10:00", data["time3"]["value"])

    def test_success_normalizes_accepted_and_consumes_grant(self) -> None:
        outcome = normalize_wechat_response(WeChatRawResponse(200, {"errcode": 0, "errmsg": "ok"}))
        self.assertEqual(ProviderOutcomeKind.ACCEPTED, outcome.kind)
        self.assertEqual(GrantEffect.CONSUME, outcome.grant_effect)
        self.assertTrue(outcome.provider_accepted)

    def test_43101_normalizes_auth_required_and_consumes_grant(self) -> None:
        outcome = normalize_wechat_response(
            WeChatRawResponse(200, {"errcode": ERR_USER_REFUSE, "errmsg": "user refuse"})
        )
        self.assertEqual(ProviderOutcomeKind.AUTH_REQUIRED, outcome.kind)
        self.assertEqual(GrantEffect.CONSUME, outcome.grant_effect)

    def test_40037_normalizes_config_blocked_and_preserves_grant(self) -> None:
        outcome = normalize_wechat_response(
            WeChatRawResponse(200, {"errcode": ERR_TEMPLATE_INVALID, "errmsg": "bad template"})
        )
        self.assertEqual(ProviderOutcomeKind.CONFIG_BLOCKED, outcome.kind)
        self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)

    def test_rate_limit_normalizes_retryable(self) -> None:
        outcome = normalize_wechat_response(
            WeChatRawResponse(200, {"errcode": ERR_RATE_LIMIT, "errmsg": "rate limit"})
        )
        self.assertEqual(ProviderOutcomeKind.RETRYABLE, outcome.kind)
        self.assertTrue(outcome.allows_automatic_retry)
        self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)

    def test_token_codes_normalize_retryable(self) -> None:
        for code in (ERR_TOKEN_INVALID, ERR_TOKEN_EXPIRED):
            with self.subTest(code=code):
                outcome = normalize_wechat_response(
                    WeChatRawResponse(200, {"errcode": code, "errmsg": "token"})
                )
                self.assertEqual(ProviderOutcomeKind.RETRYABLE, outcome.kind)
                self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)

    def test_http_5xx_normalizes_retryable(self) -> None:
        outcome = normalize_wechat_response(WeChatRawResponse(503, None))
        self.assertEqual(ProviderOutcomeKind.RETRYABLE, outcome.kind)
        self.assertEqual("HTTP_503", outcome.provider_code)
        self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)

    def test_unknown_nonzero_is_ambiguous(self) -> None:
        outcome = normalize_wechat_response(
            WeChatRawResponse(200, {"errcode": 49999, "errmsg": "unknown"})
        )
        self.assertEqual(ProviderOutcomeKind.AMBIGUOUS, outcome.kind)
        self.assertFalse(outcome.allows_automatic_retry)
        self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)

    def test_malformed_response_is_ambiguous(self) -> None:
        for body in (None, [], {"errmsg": "missing"}, {"errcode": "not-int"}):
            with self.subTest(body=body):
                outcome = normalize_wechat_response(WeChatRawResponse(200, body))
                self.assertEqual(ProviderOutcomeKind.AMBIGUOUS, outcome.kind)

    async def test_token_failure_before_send_is_retryable(self) -> None:
        adapter = WeChatSubscribeFormalAdapter(
            _Gateway(exc=WeChatTokenUnavailableError("token unavailable"))
        )
        outcome = await adapter.send(_message())
        self.assertEqual(ProviderOutcomeKind.RETRYABLE, outcome.kind)
        self.assertEqual("TOKEN_UNAVAILABLE", outcome.provider_code)

    async def test_send_transport_failure_is_ambiguous(self) -> None:
        adapter = WeChatSubscribeFormalAdapter(
            _Gateway(exc=WeChatSendAmbiguousError("response lost"))
        )
        outcome = await adapter.send(_message())
        self.assertEqual(ProviderOutcomeKind.AMBIGUOUS, outcome.kind)
        self.assertEqual("SEND_TRANSPORT_AMBIGUOUS", outcome.provider_code)

    async def test_http_gateway_builds_token_and_send_requests_without_secret_in_send_payload(self) -> None:
        seen = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if "/cgi-bin/token" in request.url.path:
                return httpx.Response(200, json={"access_token": "token-value", "expires_in": 7200})
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = HttpxWeChatProviderGateway(
                appid="app-id",
                app_secret="super-secret",
                client=client,
            )
            raw = await gateway.send(_message(), build_live_start_template_data(_message()))

        self.assertEqual(200, raw.http_status)
        self.assertEqual(2, len(seen))
        send_request = seen[1]
        payload = json.loads(send_request.content.decode("utf-8"))
        self.assertEqual("openid-user-201", payload["touser"])
        self.assertEqual("tpl-live-start", payload["template_id"])
        self.assertNotIn("super-secret", send_request.content.decode("utf-8"))
        self.assertNotIn("token-value", json.dumps(raw.body))

    async def test_http_gateway_invalidates_cached_token_on_token_error(self) -> None:
        token_calls = 0
        send_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal token_calls, send_calls
            if "/cgi-bin/token" in request.url.path:
                token_calls += 1
                return httpx.Response(
                    200,
                    json={"access_token": f"token-{token_calls}", "expires_in": 7200},
                )
            send_calls += 1
            if send_calls == 1:
                return httpx.Response(200, json={"errcode": ERR_TOKEN_INVALID, "errmsg": "bad"})
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = HttpxWeChatProviderGateway(
                appid="app-id",
                app_secret="secret",
                client=client,
            )
            first = await gateway.send(_message(), build_live_start_template_data(_message()))
            second = await gateway.send(_message(), build_live_start_template_data(_message()))

        self.assertEqual(ERR_TOKEN_INVALID, first.body["errcode"])
        self.assertEqual(0, second.body["errcode"])
        self.assertEqual(2, token_calls)

    async def test_application_acceptance_maps_to_sent(self) -> None:
        claimed = _claimed()
        state = _StateService(claimed)
        provider = _Provider(ProviderOutcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0", "ok"))
        service = WeChatDeliveryAttemptApplicationService(provider, state)  # type: ignore[arg-type]
        result = await service.execute(claimed, _message(), now=T1)
        self.assertEqual(DeliveryState.SENT, result.delivery.state)
        self.assertEqual(GrantEffect.CONSUME, result.grant_effect)

    async def test_application_auth_and_config_map_to_nonblind_states(self) -> None:
        cases = (
            (ProviderOutcomeKind.AUTH_REQUIRED, GrantEffect.CONSUME, "43101", DeliveryState.WAITING_AUTH),
            (ProviderOutcomeKind.CONFIG_BLOCKED, GrantEffect.PRESERVE, "40037", DeliveryState.BLOCKED_CONFIG),
        )
        for kind, effect, code, expected in cases:
            with self.subTest(kind=kind):
                claimed = _claimed()
                state = _StateService(claimed)
                provider = _Provider(ProviderOutcome(kind, effect, code, "detail"))
                service = WeChatDeliveryAttemptApplicationService(provider, state)  # type: ignore[arg-type]
                result = await service.execute(claimed, _message(), now=T1)
                self.assertEqual(expected, result.delivery.state)
                self.assertFalse(result.delivery.allows_blind_retry)

    async def test_application_retryable_schedules_exponential_retry(self) -> None:
        claimed = _claimed(attempt=3)
        state = _StateService(claimed)
        provider = _Provider(
            ProviderOutcome(ProviderOutcomeKind.RETRYABLE, GrantEffect.PRESERVE, "45009", "rate")
        )
        policy = WeChatRetryPolicy(base_seconds=10, max_seconds=300, max_attempts=8)
        service = WeChatDeliveryAttemptApplicationService(
            provider,
            state,  # type: ignore[arg-type]
            retry_policy=policy,
        )
        result = await service.execute(claimed, _message(), now=T1)
        self.assertEqual(DeliveryState.WAITING_RETRY, result.delivery.state)
        self.assertEqual(40, state.last_delay)

    async def test_application_retry_exhaustion_is_terminal(self) -> None:
        claimed = _claimed(attempt=8)
        state = _StateService(claimed)
        provider = _Provider(
            ProviderOutcome(ProviderOutcomeKind.RETRYABLE, GrantEffect.PRESERVE, "45009", "rate")
        )
        service = WeChatDeliveryAttemptApplicationService(provider, state)  # type: ignore[arg-type]
        result = await service.execute(claimed, _message(), now=T1)
        self.assertEqual(DeliveryState.FAILED_TERMINAL, result.delivery.state)
        self.assertTrue(result.delivery.is_terminal)
        self.assertEqual("RETRY_EXHAUSTED_45009", result.delivery.error_code)

    async def test_application_ambiguous_marks_ambiguous(self) -> None:
        claimed = _claimed()
        state = _StateService(claimed)
        provider = _Provider(
            ProviderOutcome(
                ProviderOutcomeKind.AMBIGUOUS,
                GrantEffect.PRESERVE,
                "SEND_TRANSPORT_AMBIGUOUS",
                "response lost",
            )
        )
        service = WeChatDeliveryAttemptApplicationService(provider, state)  # type: ignore[arg-type]
        result = await service.execute(claimed, _message(), now=T1)
        self.assertEqual(DeliveryState.AMBIGUOUS, result.delivery.state)
        self.assertFalse(result.delivery.allows_blind_retry)
        self.assertEqual(T0, result.delivery.in_flight_at)

    def test_provider_boundary_does_not_import_legacy_or_claim_exactly_once(self) -> None:
        def imports(path: Path) -> list[str]:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            modules = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
            return modules

        app_forbidden = (
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "httpx",
            "requests",
        )
        for path in (APP_PROVIDER_PATH, APP_SERVICE_PATH):
            for module in imports(path):
                self.assertFalse(
                    any(module == prefix or module.startswith(prefix + ".") for prefix in app_forbidden),
                    f"{path.name}: {module}",
                )

        infra_forbidden = ("api", "workers", "core", "platform_adapters", "experiments")
        for module in imports(INFRA_PATH):
            self.assertFalse(
                any(module == prefix or module.startswith(prefix + ".") for prefix in infra_forbidden),
                module,
            )
        source = APP_SERVICE_PATH.read_text(encoding="utf-8") + INFRA_PATH.read_text(encoding="utf-8")
        self.assertNotIn("exactly_once", source)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)


if __name__ == "__main__":
    unittest.main()
