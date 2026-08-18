#!/usr/bin/env python3
"""Gate 0E-2 — one-shot real WeChat handoff from a GoldenPath event.

This operator harness intentionally reuses the accepted Gate 0E GoldenPathHarness
and the accepted Gate 0D WeChat boundary. It does not invent another live-state,
eligibility, delivery, or provider-result implementation.

The source transition in this Gate harness is controlled/deterministic:
OFFLINE -> LIVE -> LIVE. The resulting TRANSITION LIVE_STARTED event and exact
logical NotificationDelivery are then used to build the real Stage Letter
subscription-message payload and cross the WeChat provider boundary exactly once.

Safety:
- provider send count is exactly one per process invocation;
- DeliveryRetryMachine enters IN_FLIGHT before the external send;
- the pre-send evidence file is written before the side effect;
- non-zero provider responses are not guessed into specific domain outcomes;
- AppSecret, access_token, session_key, login code and raw openid are never persisted;
- rerunning this operator manually is a new external send and may duplicate a message.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for relative in ("experiments/gate0e", "experiments/gate0d"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from golden_path import (  # noqa: E402
    CanonicalStatus,
    GoldenPathHarness,
    GoldenTarget,
    GrantState,
    HealthState,
    SourceObservation,
)
from provider_result import ProviderOutcome, ProviderResult, normalize_provider_result  # noqa: E402
from real_wechat_probe import (  # noqa: E402
    exchange_login_code,
    fetch_access_token,
    fingerprint,
    get_app_secret,
    provider_summary,
    send_subscribe_message,
)

ACCOUNT_ID = "douyin:gate0e-real"
TARGET_USER_ID = "gate0e-real-user"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None, *, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("datetime values must include a timezone offset")
    return parsed


def canonical_payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()[:16]


def evidence_path() -> Path:
    root = Path(tempfile.gettempdir()) / "stage-letter-gate0e"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"gate0e-real-{utc_now().strftime('%Y%m%d-%H%M%S')}.json"


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


def make_source(
    observation_id: str,
    at: datetime,
    status: CanonicalStatus,
    *,
    title: str | None = None,
    live_url: str | None = None,
    source_started_at: datetime | None = None,
) -> SourceObservation:
    return SourceObservation(
        account_id=ACCOUNT_ID,
        source_id="streamget",
        observation_id=observation_id,
        observed_at=at,
        status=status,
        health=HealthState.HEALTHY,
        title=title,
        live_url=live_url,
        source_started_at=source_started_at,
    )


def build_wechat_data(
    *,
    context,
    creator_name: str,
    room_name: str,
    activity: str,
    field_room: str,
    field_creator: str,
    field_started_at: str,
    field_title: str,
    field_activity: str,
) -> dict[str, Any]:
    started = context.source_started_at or context.occurred_at
    return {
        field_room: {"value": room_name},
        field_creator: {"value": creator_name},
        field_started_at: {"value": started.astimezone().strftime("%Y-%m-%d %H:%M")},
        field_title: {"value": context.title or "爱播开播了"},
        field_activity: {"value": activity},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate 0E-2 real golden-event handoff")
    parser.add_argument("--appid", default=os.getenv("WECHAT_APP_ID"))
    parser.add_argument("--template-id", default=os.getenv("WECHAT_TEMPLATE_ID"))
    parser.add_argument("--openid", default=os.getenv("WECHAT_OPENID"))
    parser.add_argument("--login-code", help="fresh wx.login code; never persisted")
    parser.add_argument("--creator-name", default="珩小派")
    parser.add_argument("--room-name", default="开场信 Gate 0E Golden Path")
    parser.add_argument("--activity", default="Gate 0E 真实链路验证")
    parser.add_argument("--title", default="爱播开播啦 · Gate 0E")
    parser.add_argument("--live-url", default="https://live.douyin.com/gate0e")
    parser.add_argument("--event-at", help="ISO datetime with offset; default: now")
    parser.add_argument("--source-started-at", help="ISO datetime with offset")
    parser.add_argument("--page")
    parser.add_argument(
        "--miniprogram-state",
        choices=("developer", "trial", "formal"),
        default="developer",
    )
    parser.add_argument("--lang", default="zh_CN")

    # Defaults match the currently verified Stage Letter live-start template.
    parser.add_argument("--field-room", default="thing1")
    parser.add_argument("--field-creator", default="thing2")
    parser.add_argument("--field-started-at", default="time3")
    parser.add_argument("--field-title", default="thing5")
    parser.add_argument("--field-activity", default="thing6")

    parser.add_argument("--output", help="sanitized evidence path; defaults outside repo")
    parser.add_argument(
        "--send",
        action="store_true",
        help="perform exactly one real WeChat send; otherwise build/validate only",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    appid = (args.appid or "").strip()
    template_id = (args.template_id or "").strip()
    if not appid:
        raise SystemExit("WECHAT_APP_ID / --appid is required")
    if not template_id:
        raise SystemExit("WECHAT_TEMPLATE_ID / --template-id is required")

    event_at = parse_dt(args.event_at, default=datetime.now().astimezone())
    source_started_at = parse_dt(
        args.source_started_at,
        default=event_at - timedelta(seconds=45),
    )

    with tempfile.TemporaryDirectory(prefix="stage-letter-gate0e-") as temp_dir:
        harness = GoldenPathHarness(
            db_path=Path(temp_dir) / "gate0e.sqlite3",
            account_id=ACCOUNT_ID,
            target=GoldenTarget(
                user_id=TARGET_USER_ID,
                following=True,
                notification_enabled=True,
                grant_state=GrantState.GRANTED,
            ),
        )

        harness.process_source(
            make_source("real-offline-1", event_at - timedelta(seconds=60), CanonicalStatus.OFFLINE)
        )
        harness.process_source(
            make_source("real-live-1", event_at - timedelta(seconds=30), CanonicalStatus.LIVE)
        )
        golden = harness.process_source(
            make_source(
                "real-live-2",
                event_at,
                CanonicalStatus.LIVE,
                title=args.title,
                live_url=args.live_url,
                source_started_at=source_started_at,
            )
        )

        if len(golden.notification_events) != 1:
            raise SystemExit("golden path did not emit exactly one notification event")
        if len(golden.deliveries) != 1 or golden.deliveries[0].delivery is None:
            raise SystemExit("golden path did not create exactly one logical delivery")
        if not golden.deliveries[0].created:
            raise SystemExit("golden path logical delivery was not newly created")

        notification_event = golden.notification_events[0]
        delivery = golden.deliveries[0].delivery
        context = harness.context_for_event(notification_event.event_id)
        if context is None:
            raise SystemExit("golden path did not preserve notification context")

        data = build_wechat_data(
            context=context,
            creator_name=args.creator_name,
            room_name=args.room_name,
            activity=args.activity,
            field_room=args.field_room,
            field_creator=args.field_creator,
            field_started_at=args.field_started_at,
            field_title=args.field_title,
            field_activity=args.field_activity,
        )
        provider_payload = {
            "touser": "<openid>",
            "template_id": template_id,
            "data": data,
            "miniprogram_state": args.miniprogram_state,
            "lang": args.lang,
        }
        if args.page:
            provider_payload["page"] = args.page

        output = Path(args.output) if args.output else evidence_path()
        evidence: dict[str, Any] = {
            "gate": "0E-2",
            "captured_at": utc_now().isoformat(timespec="seconds"),
            "send_requested": bool(args.send),
            "provider_send_count": 0,
            "source_transition": ["OFFLINE", "LIVE", "LIVE"],
            "event": {
                "event_id": notification_event.event_id,
                "event_type": notification_event.event_type.value,
                "cause": notification_event.cause.value,
                "session_id": notification_event.session_id,
            },
            "delivery": {
                "user_id": delivery.key.user_id,
                "live_event_id": delivery.key.live_event_id,
                "channel": delivery.key.channel.value,
                "account_id": delivery.account_id,
                "session_id": delivery.session_id,
            },
            "context": {
                "title": context.title,
                "live_url": context.live_url,
                "source_started_at": (
                    context.source_started_at.isoformat()
                    if context.source_started_at is not None
                    else None
                ),
            },
            "appid_fingerprint": fingerprint(appid),
            "template_id_fingerprint": fingerprint(template_id),
            "template_fields": sorted(data.keys()),
            "payload_fingerprint": payload_fingerprint(provider_payload),
            "openid_source": None,
            "openid_fingerprint": None,
            "token_acquired": False,
            "runtime_state_before_send": harness.runtime_for(delivery).state.value,
            "runtime_state_after_send": None,
            "provider": None,
            "phone_receipt_confirmed": False,
            "secrets_persisted": False,
        }

        if not args.send:
            write_evidence(output, evidence)
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            print(f"Evidence: {output}")
            print("Dry validation only. Re-run with --send for one real provider handoff.")
            return 0

        appsecret = get_app_secret()
        if not appsecret:
            raise SystemExit("AppSecret is required for real send")

        openid = (args.openid or "").strip()
        if not openid:
            login_code = (args.login_code or "").strip()
            if not login_code:
                raise SystemExit("WECHAT_OPENID/--openid or a fresh --login-code is required")
            session = exchange_login_code(appid, appsecret, login_code)
            openid = str(session.get("openid") or "").strip()
            if not openid:
                evidence["code2session"] = {
                    "errcode": session.get("errcode"),
                    "errmsg": session.get("errmsg"),
                    "transport_error": session.get("transport_error"),
                }
                write_evidence(output, evidence)
                print(json.dumps(evidence, ensure_ascii=False, indent=2))
                print(f"Evidence: {output}")
                return 2
            evidence["openid_source"] = "code2session"
        else:
            evidence["openid_source"] = "configured"
        evidence["openid_fingerprint"] = fingerprint(openid)

        token_response = fetch_access_token(appid, appsecret)
        access_token = str(token_response.get("access_token") or "").strip()
        if not access_token:
            evidence["token"] = {
                "errcode": token_response.get("errcode"),
                "errmsg": token_response.get("errmsg"),
                "transport_error": token_response.get("transport_error"),
            }
            write_evidence(output, evidence)
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            print(f"Evidence: {output}")
            return 3
        evidence["token_acquired"] = True

        runtime = harness.runtime_for(delivery)
        attempt_id = f"{delivery.key.live_event_id}:real-handoff:1"
        started_at = utc_now()
        begin = runtime.begin_attempt(attempt_id=attempt_id, started_at=started_at)
        if not begin.started:
            raise SystemExit(f"delivery could not enter IN_FLIGHT: {runtime.state.value}")

        # Persist pre-side-effect state before crossing the provider boundary.
        evidence["runtime_state_before_send"] = runtime.state.value
        evidence["provider_send_count"] = 0
        write_evidence(output, evidence)

        response = send_subscribe_message(
            access_token,
            openid=openid,
            template_id=template_id,
            data=data,
            page=args.page,
            miniprogram_state=args.miniprogram_state,
            lang=args.lang,
        )
        evidence["provider_send_count"] = 1
        summary = provider_summary(response)
        evidence["provider"] = summary
        if response.get("msgid") is not None:
            evidence["provider"]["msgid"] = response.get("msgid")

        if summary["normalized"] == "SENT":
            normalized = normalize_provider_result(
                ProviderResult(
                    outcome=ProviderOutcome.SENT,
                    provider_code=str(summary.get("errcode")),
                    provider_message=summary.get("errmsg"),
                )
            )
            runtime.complete_attempt(
                attempt_id=attempt_id,
                result=normalized,
                completed_at=utc_now(),
            )
            evidence["runtime_state_after_send"] = runtime.state.value
            evidence["provider_mapping_status"] = "CONFIRMED_SENT"
        else:
            # Preserve the exact raw result. Do not invent a retry/domain mapping.
            evidence["runtime_state_after_send"] = "UNRESOLVED_PROVIDER_RESULT"
            evidence["provider_mapping_status"] = "REQUIRES_MAPPING_REVIEW"

        write_evidence(output, evidence)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        print(f"Evidence: {output}")
        if summary["normalized"] == "SENT":
            print("Provider accepted the golden-event handoff. Confirm phone receipt manually.")
            return 0
        return 4


if __name__ == "__main__":
    sys.exit(main())
