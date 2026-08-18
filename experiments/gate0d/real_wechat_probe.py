#!/usr/bin/env python3
"""Gate 0D-4 — conservative real WeChat subscription-message probe.

This harness captures real provider evidence without guessing non-zero WeChat
errcode semantics. A successful send (errcode == 0) may be recorded as SENT;
all non-zero provider responses remain UNMAPPED until current provider evidence
and documentation support a concrete mapping.

Secrets are never written to evidence:
- AppSecret is read from WECHAT_APP_SECRET or prompted with getpass.
- access_token and session_key are never printed or persisted.
- login code is used only for the code2session request and is not persisted.
- openid is represented in evidence only by a SHA-256 fingerprint.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"http_status": exc.code, "http_error": "non-json response"}
        data.setdefault("http_status", exc.code)
        return data
    except urllib.error.URLError as exc:
        return {"transport_error": type(exc.reason).__name__}
    except TimeoutError:
        return {"transport_error": "TimeoutError"}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"transport_error": "NonJsonResponse"}
    if not isinstance(data, dict):
        return {"transport_error": "UnexpectedJsonShape"}
    return data


def get_app_secret() -> str:
    secret = os.getenv("WECHAT_APP_SECRET", "").strip()
    if secret:
        return secret
    return getpass.getpass("WeChat AppSecret (not echoed, not persisted): ").strip()


def fetch_access_token(appid: str, appsecret: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "grant_type": "client_credential",
            "appid": appid,
            "secret": appsecret,
        }
    )
    return request_json("GET", f"{TOKEN_URL}?{query}")


def exchange_login_code(appid: str, appsecret: str, login_code: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "appid": appid,
            "secret": appsecret,
            "js_code": login_code,
            "grant_type": "authorization_code",
        }
    )
    return request_json("GET", f"{CODE2SESSION_URL}?{query}")


def send_subscribe_message(
    access_token: str,
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

    query = urllib.parse.urlencode({"access_token": access_token})
    return request_json("POST", f"{SEND_URL}?{query}", payload=payload)


def load_data(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not value:
        raise ValueError("template data JSON must be a non-empty object")
    return value


def default_output_path() -> Path:
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "data" / f"wechat-real-{stamp}.json"


def provider_summary(response: dict[str, Any]) -> dict[str, Any]:
    errcode = response.get("errcode")
    errmsg = response.get("errmsg")
    if errcode == 0:
        normalized = "SENT"
    elif "transport_error" in response:
        normalized = "NETWORK_ERROR"
    else:
        normalized = "UNMAPPED_PROVIDER_ERROR"
    return {
        "errcode": errcode,
        "errmsg": errmsg,
        "transport_error": response.get("transport_error"),
        "normalized": normalized,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate 0D-4 real WeChat evidence probe")
    parser.add_argument("--appid", default=os.getenv("WECHAT_APP_ID"))
    parser.add_argument("--template-id", default=os.getenv("WECHAT_TEMPLATE_ID"))
    parser.add_argument("--openid", default=os.getenv("WECHAT_OPENID"))
    parser.add_argument("--login-code", help="fresh wx.login code; never persisted")
    parser.add_argument("--data-file", required=True, help="template data JSON file")
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
        help="perform the real provider send; otherwise validate inputs only",
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
        "captured_at": utc_now().isoformat(timespec="seconds"),
        "send_requested": bool(args.send),
        "appid_fingerprint": fingerprint(appid),
        "template_id_fingerprint": fingerprint(template_id),
        "miniprogram_state": args.miniprogram_state,
        "page_configured": bool(args.page),
        "template_fields": sorted(template_data.keys()),
        "openid_source": None,
        "openid_fingerprint": None,
        "token_acquired": False,
        "provider": None,
        "provider_mapping_status": "NOT_ATTEMPTED",
        "secrets_persisted": False,
    }

    if not args.send:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("Dry validation only. Re-run with --send for real provider evidence.")
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
    evidence["provider"] = summary
    evidence["provider_mapping_status"] = (
        "CONFIRMED_SENT" if summary["normalized"] == "SENT" else "REQUIRES_MAPPING_REVIEW"
    )

    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"Evidence: {output}")
    return 0 if summary["normalized"] == "SENT" else 4


if __name__ == "__main__":
    sys.exit(main())
