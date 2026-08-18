#!/usr/bin/env python3
"""Gate 0D-4 — controlled exact-payload WeChat replay probe.

This operator tool intentionally performs two provider calls with the same
access token and the same request body in one process. It exists only to capture
real replay/idempotency evidence. It must not be used as a production retry
mechanism.

Secrets are never persisted:
- AppSecret is read from WECHAT_APP_SECRET or prompted without echo.
- access_token, session_key, login code and raw openid are never written.
- the request body is represented only by a SHA-256 fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from real_wechat_probe import (
    exchange_login_code,
    fetch_access_token,
    fingerprint,
    get_app_secret,
    load_data,
    provider_summary,
    send_subscribe_message,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_payload(
    *,
    openid: str,
    template_id: str,
    data: dict[str, Any],
    page: str | None,
    miniprogram_state: str,
    lang: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "touser": openid,
        "template_id": template_id,
        "data": data,
        "miniprogram_state": miniprogram_state,
        "lang": lang,
    }
    if page:
        payload["page"] = page
    return payload


def payload_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def default_output_path() -> Path:
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "data" / f"wechat-replay-{stamp}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate 0D-4 exact replay evidence probe")
    parser.add_argument("--appid", default=os.getenv("WECHAT_APP_ID"))
    parser.add_argument("--template-id", default=os.getenv("WECHAT_TEMPLATE_ID"))
    parser.add_argument("--openid", default=os.getenv("WECHAT_OPENID"))
    parser.add_argument("--login-code", help="fresh wx.login code; never persisted")
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--page")
    parser.add_argument(
        "--miniprogram-state",
        choices=("developer", "trial", "formal"),
        default="developer",
    )
    parser.add_argument("--lang", default="zh_CN")
    parser.add_argument("--output")
    parser.add_argument(
        "--send",
        action="store_true",
        help="perform exactly two real provider calls; otherwise dry validation only",
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

    template_data = load_data(args.data_file)
    evidence: dict[str, Any] = {
        "gate": "0D-4",
        "experiment": "EXACT_PAYLOAD_REPLAY",
        "captured_at": utc_now().isoformat(timespec="seconds"),
        "send_requested": bool(args.send),
        "replay_count": 2,
        "same_access_token_for_both_calls": bool(args.send),
        "appid_fingerprint": fingerprint(appid),
        "template_id_fingerprint": fingerprint(template_id),
        "openid_source": None,
        "openid_fingerprint": None,
        "request_payload_fingerprint": None,
        "template_fields": sorted(template_data.keys()),
        "miniprogram_state": args.miniprogram_state,
        "page_configured": bool(args.page),
        "token_acquired": False,
        "provider_attempts": [],
        "secrets_persisted": False,
    }

    if not args.send:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("Dry validation only. Re-run with --send for two exact provider calls.")
        return 0

    appsecret = get_app_secret()
    if not appsecret:
        raise SystemExit("AppSecret is required for real replay send")

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
            output = Path(args.output) if args.output else default_output_path()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            print(f"Evidence: {output}")
            return 2
        evidence["openid_source"] = "code2session"
    else:
        evidence["openid_source"] = "configured"

    evidence["openid_fingerprint"] = fingerprint(openid)
    payload = canonical_payload(
        openid=openid,
        template_id=template_id,
        data=template_data,
        page=args.page,
        miniprogram_state=args.miniprogram_state,
        lang=args.lang,
    )
    evidence["request_payload_fingerprint"] = payload_fingerprint(payload)

    token_response = fetch_access_token(appid, appsecret)
    access_token = str(token_response.get("access_token") or "").strip()
    if not access_token:
        evidence["token"] = {
            "errcode": token_response.get("errcode"),
            "errmsg": token_response.get("errmsg"),
            "transport_error": token_response.get("transport_error"),
        }
        output = Path(args.output) if args.output else default_output_path()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        print(f"Evidence: {output}")
        return 3

    evidence["token_acquired"] = True

    for attempt_number in (1, 2):
        response = send_subscribe_message(
            access_token,
            openid=openid,
            template_id=template_id,
            data=template_data,
            page=args.page,
            miniprogram_state=args.miniprogram_state,
            lang=args.lang,
        )
        summary = provider_summary(response)
        attempt: dict[str, Any] = {
            "attempt": attempt_number,
            "captured_at": utc_now().isoformat(timespec="milliseconds"),
            **summary,
        }
        if response.get("msgid") is not None:
            attempt["msgid"] = response.get("msgid")
        evidence["provider_attempts"].append(attempt)

    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"Evidence: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
