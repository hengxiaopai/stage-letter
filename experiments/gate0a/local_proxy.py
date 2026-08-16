#!/usr/bin/env python3
"""Local-only Stage Letter Gate 0A proxy for WeChat DevTools.

Security boundary:
- Reads TikHub token only from TIKHUB_API_KEY.
- Never returns or logs the token.
- Exposes normalized Gate 0A observations only.
- Not a production backend and does not create LiveSession/notifications.

Identity boundary:
- Weak nickname containment is never authoritative for live-state probing.
- Exact nickname / exact Douyin ID is required before creator-status lookup.
- For ambiguous names, callers must choose a concrete account (prefer Douyin ID).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tikhub_creator_status_probe import probe_uid_live, search_users
from tikhub_creator_status_v2 import resolve_and_probe_v2
from tikhub_live_search_probe import fetch_live_search
from tikhub_probe import probe_target

HOST = os.environ.get("STAGE_LETTER_GATE0A_HOST", "127.0.0.1")
PORT = int(os.environ.get("STAGE_LETTER_GATE0A_PORT", "8765"))
EXACT_MATCH_REASONS = {"EXACT_NICKNAME", "EXACT_DOUYIN_ID"}


def get_token() -> str:
    return os.environ.get("TIKHUB_API_KEY", "").strip()


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def missing_secret() -> dict:
    return {
        "ok": False,
        "status": "UNKNOWN",
        "error_type": "BLOCKED_MISSING_SECRET",
        "message": "TIKHUB_API_KEY is not configured in the local server environment",
    }


def safe_observation(webcast_id: str, label: str = "") -> dict:
    token = get_token()
    if not token:
        return missing_secret()
    target = {"id": "LOCAL-GATE0A", "label": label or webcast_id, "web_rid": webcast_id}
    obs = probe_target(target, token, timeout=20.0)
    raw = asdict(obs)
    return {
        "ok": True,
        "platform": "douyin",
        "webcast_id": raw["webcast_id"],
        "status": raw["status"],
        "creator_name": raw["creator_name"],
        "title": raw["title"],
        "room_id": raw["room_id"],
        "stream_url_count": raw["stream_url_count"],
        "observed_at": raw["observed_at"],
        "source_type": raw["source_type"],
        "source_provider": raw["source_provider"],
        "confidence": raw["confidence"],
        "http_status": raw["http_status"],
        "latency_ms": raw["latency_ms"],
        "provider_code": raw["provider_code"],
        "provider_message": raw["provider_message"],
        "error_type": raw["error_type"],
        "evidence": raw["evidence"],
        "production_approved": False,
    }


def safe_live_search(keyword: str) -> dict:
    token = get_token()
    if not token:
        return missing_secret()
    return fetch_live_search(keyword, token, timeout=30.0)


def safe_creator_search(keyword: str) -> dict:
    token = get_token()
    if not token:
        return missing_secret()
    result = search_users(keyword, token, timeout=30.0)
    return {
        "ok": result.get("ok", False),
        "platform": "douyin",
        "keyword": keyword,
        "candidate_count": result.get("candidate_count", 0),
        "candidates": result.get("candidates", []),
        "selected": result.get("selected"),
        "match_reason": result.get("match_reason"),
        "http_status": result.get("http_status"),
        "latency_ms": result.get("latency_ms"),
        "provider_code": result.get("provider_code"),
        "provider_message": result.get("provider_message"),
        "source_type": "COMMERCIAL_API_CANDIDATE",
        "source_provider": "TIKHUB",
        "source_endpoint": result.get("source_endpoint"),
        "attempts": result.get("attempts", []),
        "production_approved": False,
        "error_type": result.get("error_type"),
    }


def ambiguous_creator_result(identifier: str, search: dict) -> dict:
    selected = search.get("selected")
    candidates = search.get("candidates") or []
    return {
        "ok": False,
        "platform": "douyin",
        "keyword": identifier,
        "status": "UNKNOWN",
        "creator": selected,
        "room_id": None,
        "observed_at": now_iso(),
        "confidence": 0.0,
        "evidence": [
            f"creator_match:{search.get('match_reason')}",
            "weak_identity_match_not_authoritative",
        ],
        "identity_resolution": {
            "match_reason": search.get("match_reason"),
            "candidate_count": search.get("candidate_count", 0),
            "requires_exact_identity": True,
            "preferred_input": "douyin_id",
            "candidate_preview": [
                {
                    "uid": item.get("uid"),
                    "nickname": item.get("nickname"),
                    "unique_id": item.get("unique_id"),
                    "avatar_url": item.get("avatar_url"),
                }
                for item in candidates[:10]
            ],
        },
        "source_type": "COMMERCIAL_API_CANDIDATE",
        "source_provider": "TIKHUB",
        "production_approved": False,
        "error_type": "AMBIGUOUS_CREATOR_IDENTITY",
    }


def safe_creator_status(identifier: str) -> dict:
    token = get_token()
    if not token:
        return missing_secret()

    # A numeric Douyin ID is already a strong user-supplied identity key; let the
    # resolver confirm it via EXACT_DOUYIN_ID without doing an extra paid search.
    if re.fullmatch(r"\d{5,30}", identifier):
        return resolve_and_probe_v2(identifier, token, timeout=30.0)

    # Text nicknames are allowed only when creator search produces an exact
    # identity match. NICKNAME_CONTAINS/FIRST_SEARCH_RESULT are discovery hints,
    # never authoritative live-status targets.
    preflight = search_users(identifier, token, timeout=30.0)
    if preflight.get("match_reason") not in EXACT_MATCH_REASONS:
        return ambiguous_creator_result(identifier, preflight)

    return resolve_and_probe_v2(identifier, token, timeout=30.0)


def safe_uid_live(uid: str) -> dict:
    token = get_token()
    if not token:
        return missing_secret()
    result = probe_uid_live(uid, token, timeout=30.0)
    return {
        **result,
        "platform": "douyin",
        "observed_at": now_iso(),
        "source_type": "COMMERCIAL_API_CANDIDATE",
        "source_provider": "TIKHUB",
        "production_approved": False,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "StageLetterGate0A/0.7"

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("[gate0a] " + (fmt % args) + "\n")

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _query_value(self, query: dict, key: str, default: str = "") -> str:
        return (query.get(key) or [default])[0].strip()

    def _validate_keyword(self, keyword: str) -> bool:
        return bool(keyword) and len(keyword) <= 80

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": "stage-letter-gate0a-local-proxy",
                "secret_configured": bool(get_token()),
                "production": False,
                "version": "0.7",
                "primary_douyin_path": "verified identity -> uid-live -> explicit status corroboration",
                "identity_policy": "exact nickname or exact douyin_id required",
            })
            return

        query = parse_qs(parsed.query)

        if parsed.path == "/api/gate0a/douyin/creator-search":
            keyword = self._query_value(query, "keyword", "X.四五六")
            if not self._validate_keyword(keyword):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_KEYWORD"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_creator_search(keyword))
            except Exception as exc:
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "LOCAL_PROXY_ERROR", "message": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path == "/api/gate0a/douyin/creator-status":
            douyin_id = self._query_value(query, "douyin_id")
            keyword = self._query_value(query, "keyword", "X.四五六")
            identifier = douyin_id or keyword
            if not self._validate_keyword(identifier):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_CREATOR_IDENTIFIER"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                result = safe_creator_status(identifier)
                result["identity_input_type"] = "DOUYIN_ID" if douyin_id else "KEYWORD"
                self._send_json(result)
            except Exception as exc:
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "LOCAL_PROXY_ERROR", "message": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path == "/api/gate0a/douyin/uid-live":
            uid = self._query_value(query, "uid")
            if not re.fullmatch(r"\d{5,30}", uid):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_UID"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_uid_live(uid))
            except Exception as exc:
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "LOCAL_PROXY_ERROR", "message": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path == "/api/gate0a/douyin/live-search":
            keyword = self._query_value(query, "keyword", "游戏") or "游戏"
            if not self._validate_keyword(keyword):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_KEYWORD"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_live_search(keyword))
            except Exception as exc:
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "LOCAL_PROXY_ERROR", "message": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path == "/api/gate0a/douyin/live":
            webcast_id = self._query_value(query, "webcast_id") or self._query_value(query, "web_rid")
            label = self._query_value(query, "label")
            if not re.fullmatch(r"\d{5,20}", webcast_id):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_TARGET", "message": "webcast_id must be 5-20 decimal digits"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_observation(webcast_id, label))
            except Exception as exc:
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "LOCAL_PROXY_ERROR", "message": type(exc).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"ok": False, "error_type": "NOT_FOUND"}, HTTPStatus.NOT_FOUND)


def main() -> int:
    configured = bool(get_token())
    print(f"Stage Letter Gate 0A local proxy: http://{HOST}:{PORT}")
    print(f"TIKHUB_API_KEY configured: {'yes' if configured else 'no'}")
    print("Primary Douyin path: verified identity -> uid-live -> explicit status corroboration")
    print("Production approved: no")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
