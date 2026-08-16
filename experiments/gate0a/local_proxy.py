#!/usr/bin/env python3
"""Local-only Stage Letter Gate 0A proxy for WeChat DevTools.

Security boundary:
- Reads TikHub token only from TIKHUB_API_KEY.
- Never returns or logs the token.
- Exposes normalized Gate 0A observations only.
- Not a production backend and does not create LiveSession/notifications.
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

from tikhub_creator_status_probe import probe_uid_live, resolve_and_probe, search_users
from tikhub_live_search_probe import fetch_live_search
from tikhub_probe import probe_target

HOST = os.environ.get("STAGE_LETTER_GATE0A_HOST", "127.0.0.1")
PORT = int(os.environ.get("STAGE_LETTER_GATE0A_PORT", "8765"))


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


def safe_creator_status(keyword: str) -> dict:
    token = get_token()
    if not token:
        return missing_secret()
    return resolve_and_probe(keyword, token, timeout=30.0)


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
    server_version = "StageLetterGate0A/0.5"

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
                "version": "0.5",
                "primary_douyin_path": "creator-search -> uid -> live_status",
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
            keyword = self._query_value(query, "keyword", "X.四五六")
            if not self._validate_keyword(keyword):
                self._send_json({"ok": False, "status": "UNKNOWN", "error_type": "INVALID_KEYWORD"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_creator_status(keyword))
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
    print("Primary Douyin path: creator-search -> uid -> live_status")
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
