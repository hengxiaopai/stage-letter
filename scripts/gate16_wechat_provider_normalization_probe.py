#!/usr/bin/env python3
"""Gate 1.6-4 deterministic WeChat provider-normalization acceptance probe.

No real WeChat request, access token, app secret, or provider account is used.
Real-account delivery acceptance is intentionally deferred to Gate 1.6-5.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage_letter.application.notification_providers import (
    GrantEffect,
    ProviderOutcome,
    ProviderOutcomeKind,
    WeChatLiveStartMessage,
)
from stage_letter.application.services.wechat_delivery import (
    WeChatDeliveryAttemptApplicationService,
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
    WeChatRawResponse,
    WeChatSendAmbiguousError,
    WeChatSubscribeFormalAdapter,
    WeChatTokenUnavailableError,
)

EXPECTED_HEAD = "a63f4b2d9e71"
NOW = datetime(2026, 8, 20, 2, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 20, 2, 31, tzinfo=timezone.utc)


class _Gateway:
    def __init__(self, raw=None, exc=None):
        self.raw = raw
        self.exc = exc
        self.calls = 0

    async def send(self, message, data):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.raw


class _Provider:
    def __init__(self, outcome):
        self.outcome = outcome

    async def send(self, message):
        return self.outcome


class _State:
    def __init__(self, delivery):
        self.delivery = delivery

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
        self.delivery = schedule_delivery_retry(
            self.delivery,
            now=now,
            delay_seconds=delay_seconds,
            error_code=error_code,
            error_message=error_message,
        )
        return self.delivery


def _message():
    return WeChatLiveStartMessage(
        openid="probe-openid",
        template_id="probe-template",
        anchor_name="Probe Anchor",
        room_title="Probe Room",
        start_time="2026-08-20 10:30",
    )


def _claimed():
    pending = NotificationDelivery(
        key=DeliveryKey("201", "probe-event", DeliveryChannel.WECHAT_SUBSCRIBE),
        account_id="101",
        session_id="301",
        created_at=NOW,
    )
    return claim_delivery(pending, now=NOW)


async def _normalized(raw=None, exc=None):
    adapter = WeChatSubscribeFormalAdapter(_Gateway(raw=raw, exc=exc))
    outcome = await adapter.send(_message())
    return {
        "kind": outcome.kind.value,
        "grant_effect": outcome.grant_effect.value,
        "provider_code": outcome.provider_code,
        "automatic_retry": outcome.allows_automatic_retry,
    }


async def _state(outcome):
    claimed = _claimed()
    state = _State(claimed)
    service = WeChatDeliveryAttemptApplicationService(
        _Provider(outcome),
        state,  # type: ignore[arg-type]
    )
    result = await service.execute(claimed, _message(), now=LATER)
    return {
        "state": result.delivery.state.value,
        "grant_effect": result.grant_effect.value,
        "blind_retry": result.delivery.allows_blind_retry,
    }


async def _main() -> int:
    matrix = {
        "0": await _normalized(WeChatRawResponse(200, {"errcode": 0, "errmsg": "ok"})),
        "43101": await _normalized(
            WeChatRawResponse(200, {"errcode": ERR_USER_REFUSE, "errmsg": "user refuse"})
        ),
        "40037": await _normalized(
            WeChatRawResponse(200, {"errcode": ERR_TEMPLATE_INVALID, "errmsg": "bad template"})
        ),
        "45009": await _normalized(
            WeChatRawResponse(200, {"errcode": ERR_RATE_LIMIT, "errmsg": "rate limit"})
        ),
        "40001": await _normalized(
            WeChatRawResponse(200, {"errcode": ERR_TOKEN_INVALID, "errmsg": "bad token"})
        ),
        "42001": await _normalized(
            WeChatRawResponse(200, {"errcode": ERR_TOKEN_EXPIRED, "errmsg": "expired token"})
        ),
        "unknown": await _normalized(
            WeChatRawResponse(200, {"errcode": 49999, "errmsg": "unknown"})
        ),
        "http_503": await _normalized(WeChatRawResponse(503, None)),
        "token_unavailable": await _normalized(exc=WeChatTokenUnavailableError("token unavailable")),
        "send_transport": await _normalized(exc=WeChatSendAmbiguousError("response lost")),
    }

    states = {
        "accepted": await _state(
            ProviderOutcome(ProviderOutcomeKind.ACCEPTED, GrantEffect.CONSUME, "0")
        ),
        "auth_required": await _state(
            ProviderOutcome(ProviderOutcomeKind.AUTH_REQUIRED, GrantEffect.CONSUME, "43101")
        ),
        "config_blocked": await _state(
            ProviderOutcome(ProviderOutcomeKind.CONFIG_BLOCKED, GrantEffect.PRESERVE, "40037")
        ),
        "retryable": await _state(
            ProviderOutcome(ProviderOutcomeKind.RETRYABLE, GrantEffect.PRESERVE, "45009")
        ),
        "ambiguous": await _state(
            ProviderOutcome(
                ProviderOutcomeKind.AMBIGUOUS,
                GrantEffect.PRESERVE,
                "SEND_TRANSPORT_AMBIGUOUS",
            )
        ),
    }

    checks = {
        "success_accepted": matrix["0"]["kind"] == "ACCEPTED" and matrix["0"]["grant_effect"] == "CONSUME",
        "refuse_waits_auth": matrix["43101"]["kind"] == "AUTH_REQUIRED" and matrix["43101"]["grant_effect"] == "CONSUME",
        "template_blocks_config": matrix["40037"]["kind"] == "CONFIG_BLOCKED",
        "rate_limit_retryable": matrix["45009"]["kind"] == "RETRYABLE",
        "token_codes_retryable": matrix["40001"]["kind"] == "RETRYABLE" and matrix["42001"]["kind"] == "RETRYABLE",
        "unknown_is_ambiguous": matrix["unknown"]["kind"] == "AMBIGUOUS",
        "token_failure_pre_send_retryable": matrix["token_unavailable"]["kind"] == "RETRYABLE",
        "send_transport_ambiguous": matrix["send_transport"]["kind"] == "AMBIGUOUS",
        "accepted_maps_sent": states["accepted"]["state"] == "SENT",
        "auth_maps_waiting_auth": states["auth_required"]["state"] == "WAITING_AUTH",
        "config_maps_blocked": states["config_blocked"]["state"] == "BLOCKED_CONFIG",
        "retry_maps_waiting_retry": states["retryable"]["state"] == "WAITING_RETRY",
        "ambiguous_not_blind_retry": states["ambiguous"]["state"] == "AMBIGUOUS" and not states["ambiguous"]["blind_retry"],
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    print(
        json.dumps(
            {
                "gate": "1.6-4",
                "status": status,
                "migration_head_expected": EXPECTED_HEAD,
                "normalization": matrix,
                "state_mapping": states,
                "checks": checks,
                "real_wechat_called": False,
                "access_token_loaded": False,
                "app_secret_loaded": False,
                "provider_exactly_once_claimed": False,
                "notification_exactly_once_claimed": False,
                "production_approved": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
