from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.domain.creators import PlatformAccount
from stage_letter.domain.live import LiveStatus
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
    classify_exception,
    classify_http_failure,
    normalize_explicit_status,
    unknown_snapshot_for_failure,
)


ROOT = Path(__file__).resolve().parents[2]
FAILURES_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "failures.py"


class ProviderFailureNormalizationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = PlatformAccount(
            account_id="200",
            creator_id="100",
            platform="douyin",
            platform_user_id="provider-user-1",
            room_id="room-1",
            canonical_url="https://example.invalid/live/room-1",
        )
        self.now = datetime(2026, 8, 19, 4, 20, tzinfo=timezone.utc)

    def test_failure_vocabulary_is_diagnostic_not_live_status(self) -> None:
        self.assertEqual(
            {
                "TIMEOUT",
                "NETWORK",
                "FORBIDDEN",
                "RATE_LIMITED",
                "AUTH_REQUIRED",
                "CAPTCHA_REQUIRED",
                "PARSE_ERROR",
                "SCHEMA_DRIFT",
                "AMBIGUOUS",
                "NOT_FOUND",
                "UPSTREAM_ERROR",
                "UNKNOWN",
            },
            {item.value for item in ProviderFailureKind},
        )
        self.assertTrue({item.value for item in ProviderFailureKind}.isdisjoint({"LIVE", "OFFLINE"}))

    def test_http_failure_classification_is_explicit(self) -> None:
        cases = {
            401: ProviderFailureKind.AUTH_REQUIRED,
            403: ProviderFailureKind.FORBIDDEN,
            404: ProviderFailureKind.NOT_FOUND,
            429: ProviderFailureKind.RATE_LIMITED,
            500: ProviderFailureKind.UPSTREAM_ERROR,
            503: ProviderFailureKind.UPSTREAM_ERROR,
            418: ProviderFailureKind.UNKNOWN,
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                failure = classify_http_failure(status, source="provider-a")
                self.assertIs(expected, failure.kind)
                self.assertEqual(status, failure.http_status)

    def test_exception_classification_only_infers_safe_transport_categories(self) -> None:
        self.assertIs(
            ProviderFailureKind.TIMEOUT,
            classify_exception(TimeoutError("slow"), source="provider-a").kind,
        )
        self.assertIs(
            ProviderFailureKind.NETWORK,
            classify_exception(ConnectionError("down"), source="provider-a").kind,
        )
        self.assertIs(
            ProviderFailureKind.UNKNOWN,
            classify_exception(RuntimeError("opaque"), source="provider-a").kind,
        )

    def test_every_failure_kind_normalizes_live_truth_to_unknown(self) -> None:
        for kind in ProviderFailureKind:
            with self.subTest(kind=kind):
                snapshot = unknown_snapshot_for_failure(
                    self.account,
                    observed_at=self.now,
                    failure=ProviderFailure(kind=kind, source="provider-a"),
                )
                self.assertIs(LiveStatus.UNKNOWN, snapshot.status)
                self.assertIsNot(LiveStatus.OFFLINE, snapshot.status)

    def test_failure_snapshot_preserves_external_identity_and_source(self) -> None:
        snapshot = unknown_snapshot_for_failure(
            self.account,
            observed_at=self.now,
            failure=ProviderFailure(
                kind=ProviderFailureKind.AMBIGUOUS,
                source="provider-a:status",
            ),
        )
        self.assertEqual("douyin", snapshot.platform)
        self.assertEqual("provider-user-1", snapshot.platform_user_id)
        self.assertEqual("room-1", snapshot.room_id)
        self.assertEqual(self.account.canonical_url, snapshot.canonical_url)
        self.assertEqual("provider-a:status", snapshot.source)
        self.assertEqual(self.now, snapshot.observed_at)

    def test_failure_snapshot_does_not_invent_live_metadata(self) -> None:
        snapshot = unknown_snapshot_for_failure(
            self.account,
            observed_at=self.now,
            failure=ProviderFailure(
                kind=ProviderFailureKind.SCHEMA_DRIFT,
                source="provider-a",
                detail="missing live_status field",
            ),
        )
        self.assertIsNone(snapshot.source_started_at)
        self.assertIsNone(snapshot.title)

    def test_explicit_provider_values_may_map_to_live_or_offline(self) -> None:
        self.assertIs(
            LiveStatus.LIVE,
            normalize_explicit_status(2, live_values=(2,), offline_values=(4,)),
        )
        self.assertIs(
            LiveStatus.OFFLINE,
            normalize_explicit_status(4, live_values=(2,), offline_values=(4,)),
        )

    def test_unrecognized_or_missing_provider_status_stays_unknown(self) -> None:
        for raw in (None, 0, 3, "blocked", "parse_error"):
            with self.subTest(raw=raw):
                self.assertIs(
                    LiveStatus.UNKNOWN,
                    normalize_explicit_status(raw, live_values=(2,), offline_values=(4,)),
                )

    def test_overlapping_explicit_status_sets_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "disjoint"):
            normalize_explicit_status(2, live_values=(1, 2), offline_values=(2, 3))

    def test_provider_operation_error_carries_normalized_failure_without_truth_claim(self) -> None:
        failure = ProviderFailure(
            kind=ProviderFailureKind.CAPTCHA_REQUIRED,
            source="provider-a",
            provider_code="captcha",
        )
        error = ProviderOperationError(failure)
        self.assertIs(failure, error.failure)
        self.assertIn("CAPTCHA_REQUIRED", str(error))
        self.assertNotIn("OFFLINE", str(error))

    def test_failure_normalizer_does_not_import_legacy_or_own_session_event_logic(self) -> None:
        source = FAILURES_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FAILURES_PATH))
        forbidden = ("api", "workers", "core", "platform_adapters", "experiments")
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(module)
        self.assertEqual([], violations)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)


if __name__ == "__main__":
    unittest.main()
