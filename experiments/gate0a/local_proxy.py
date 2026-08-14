#!/usr/bin/env python3
"""Local-only Stage Letter Gate 0A proxy for WeChat DevTools.

Security boundary:
- Reads TikHub token only from TIKHUB_API_KEY.
- Never returns or logs the token.
- Exposes only normalized Gate 0A observations.
- Not a production backend and does not create LiveSession/notifications.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tikhub_live_search_probe import fetch_live_search
from tikhub_probe import probe_target

HOST = os.environ.get("STAGE_LETTER_GATE0A_HOST", "127.0.0.1")
PORT = int(os.environ.get("STAGE_LETTER_GATE0A_PORT", "8765"))


def get_token() -> str:
    return os.environ.get("TIKHUB_API_KEY", "").strip()


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

    target = {
        "id": "LOCAL-GATE0A",
        "label": label or webcast_id,
        "web_rid": webcast_id,
    }
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
    return fetch_live_search(keyword, token, timeout=20.0)


class Handler(BaseHTTPRequestHandler):
    server_version = "StageLetterGate0A/0.3"

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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": "stage-letter-gate0a-local-proxy",
                "secret_configured": bool(get_token()),
                "production": False,
                "version": "0.3",
            })
            return

        query = parse_qs(parsed.query)

        if parsed.path == "/api/gate0a/douyin/live-search":
            keyword = (query.get("keyword") or ["游戏"])[0].strip() or "游戏"
            if len(keyword) > 40:
                self._send_json({
                    "ok": False,
                    "status": "UNKNOWN",
                    "error_type": "INVALID_KEYWORD",
                }, HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(safe_live_search(keyword))
            except Exception as exc:
                self._send_json({
                    "ok": False,
                    "status": "UNKNOWN",
                    "error_type": "LOCAL_PROXY_ERROR",
                    "message": type(exc).__name__,
                }, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path != "/api/gate0a/douyin/live":
            self._send_json({"ok": False, "error_type": "NOT_FOUND"}, HTTPStatus.NOT_FOUND)
            return

        webcast_id = (query.get("webcast_id") or query.get("web_rid") or [""])[0].strip()
        label = (query.get("label") or [""])[0].strip()
        if not re.fullmatch(r"\d{5,20}", webcast_id):
            self._send_json({
                "ok": False,
                "status": "UNKNOWN",
                "error_type": "INVALID_TARGET",
                "message": "webcast_id must be 5-20 decimal digits",
            }, HTTPStatus.BAD_REQUEST)
            return

        try:
            self._send_json(safe_observation(webcast_id, label))
        except Exception as exc:
            self._send_json({
                "ok": False,
                "status": "UNKNOWN",
                "error_type": "LOCAL_PROXY_ERROR",
                "message": type(exc).__name__,
            }, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> int:
    configured = bool(get_token())
    print(f"Stage Letter Gate 0A local proxy: http://{HOST}:{PORT}")
    print(f"TIKHUB_API_KEY configured: {'yes' if configured else 'no'}")
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
