#!/usr/bin/env python3
"""Stage Letter Gate 0A creator-status verifier with explicit OFFLINE corroboration.

Primary fact source remains fetch_user_live_info_by_uid. When that endpoint is
HTTP-successful but returns no decisive live_status, this wrapper queries the
current Douyin App user-search endpoint and only accepts LIVE/OFFLINE when the
same creator is matched and an explicit live_status (0/1) is present.

No null/absence is ever treated as OFFLINE.
"""

from __future__ import annotations

from typing import Any

from tikhub_creator_status_probe import (
    classify_live_status,
    extract_user_candidates,
    normalize_text,
    request_json,
    resolve_and_probe,
)

APP_USER_SEARCH_STATUS_ENDPOINT = "/api/v1/douyin/search/fetch_user_search"


def _same_creator(reference: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    uid = str(reference.get("uid") or "").strip()
    unique_id = normalize_text(reference.get("unique_id"))
    nickname = normalize_text(reference.get("nickname"))

    if uid:
        for candidate in candidates:
            if str(candidate.get("uid") or "").strip() == uid:
                return candidate, "EXACT_UID"
    if unique_id:
        for candidate in candidates:
            if normalize_text(candidate.get("unique_id")) == unique_id:
                return candidate, "EXACT_DOUYIN_ID"
    if nickname:
        for candidate in candidates:
            if normalize_text(candidate.get("nickname")) == nickname:
                return candidate, "EXACT_NICKNAME"
    return None, None


def _attempt_summary(call: dict[str, Any], keyword: str, candidates: list[dict[str, Any]], matched: dict[str, Any] | None, match_reason: str | None) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "http_status": call.get("http_status"),
        "provider_code": call.get("provider_code"),
        "provider_message": call.get("provider_message"),
        "latency_ms": call.get("latency_ms"),
        "error_type": call.get("error_type"),
        "candidate_count": len(candidates),
        "matched": bool(matched),
        "match_reason": match_reason,
    }


def corroborate_creator_status(reference: dict[str, Any], token: str, timeout: float = 30.0) -> dict[str, Any]:
    keywords: list[str] = []
    for value in (reference.get("unique_id"), reference.get("nickname")):
        text = str(value or "").strip()
        if text and text not in keywords:
            keywords.append(text)

    attempts: list[dict[str, Any]] = []
    for keyword in keywords[:2]:
        call = request_json(
            method="POST",
            path=APP_USER_SEARCH_STATUS_ENDPOINT,
            token=token,
            body={
                "keyword": keyword,
                "cursor": 0,
                "douyin_user_fans": "",
                "douyin_user_type": "",
                "search_id": "",
            },
            timeout=timeout,
        )
        candidates = extract_user_candidates(call.get("payload") or {}) if call.get("ok") else []
        matched, match_reason = _same_creator(reference, candidates)
        attempts.append(_attempt_summary(call, keyword, candidates, matched, match_reason))

        if matched:
            raw = matched.get("raw_live_status")
            status = classify_live_status(raw) or "UNKNOWN"
            if status in ("LIVE", "OFFLINE"):
                return {
                    "ok": True,
                    "status": status,
                    "raw_live_status": raw,
                    "matched_uid": matched.get("uid"),
                    "matched_unique_id": matched.get("unique_id"),
                    "match_reason": match_reason,
                    "source_endpoint": "fetch_user_search",
                    "attempts": attempts,
                    "error_type": None,
                }

    return {
        "ok": False,
        "status": "UNKNOWN",
        "raw_live_status": None,
        "matched_uid": None,
        "matched_unique_id": None,
        "match_reason": None,
        "source_endpoint": "fetch_user_search",
        "attempts": attempts,
        "error_type": "NO_EXPLICIT_CORROBORATING_STATUS",
    }


def resolve_and_probe_v2(keyword: str, token: str, timeout: float = 30.0) -> dict[str, Any]:
    result = resolve_and_probe(keyword, token, timeout)

    if result.get("status") in ("LIVE", "OFFLINE"):
        result["status_corroboration"] = None
        return result

    creator = result.get("creator")
    if not isinstance(creator, dict) or not creator.get("uid"):
        result["status_corroboration"] = None
        return result

    corroboration = corroborate_creator_status(creator, token, timeout)
    result["status_corroboration"] = corroboration

    if corroboration.get("status") in ("LIVE", "OFFLINE"):
        result["status"] = corroboration["status"]
        result["ok"] = True
        result["confidence"] = 0.90
        result["evidence"] = list(result.get("evidence") or []) + [
            f"corroboration_match:{corroboration.get('match_reason')}",
            f"app_user_search_live_status:{corroboration.get('raw_live_status')}",
            "uid_live_endpoint_inconclusive_explicit_app_status_used",
        ]
        result["error_type"] = None

    return result
