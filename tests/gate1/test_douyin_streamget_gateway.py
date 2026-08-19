from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.infrastructure.platforms.douyin_streamget import (
    STREAMGET_DOUYIN_SOURCE,
    StreamGetDouyinGateway,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = (
    ROOT / "stage_letter" / "infrastructure" / "platforms" / "douyin_streamget.py"
)
NOW = datetime(2026, 8, 19, 5, 0, tzinfo=timezone.utc)


class _Client:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {
            "status": 2,
            "anchor_name": "Creator",
            "id": "900",
            "title": "Live title",
            "start_time": 1787112000,
        }
        self.error: BaseException | None = None
        self.urls: list[str] = []

    async def fetch_app_stream_data(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.payload


class StreamGetDouyinGatewayContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(
        self,
        payload: dict[str, object] | None = None,
    ) -> tuple[StreamGetDouyinGateway, _Client, list[str | None]]:
        client = _Client(payload)
        cookies: list[str | None] = []

        def factory(cookie: str | None) -> _Client:
            cookies.append(cookie)
            return client

        gateway = StreamGetDouyinGateway(
            cookie=" cookie-value ",
            client_factory=factory,
            clock=lambda: NOW,
        )
        return gateway, client, cookies

    async def test_raw_sec_uid_resolution_uses_stable_profile_url(self) -> None:
        gateway, client, _ = self._build()
        record = await gateway.resolve_identity("sec_uid_abc")
        self.assertEqual("sec_uid_abc", record.sec_uid)
        self.assertEqual("https://www.douyin.com/user/sec_uid_abc", record.canonical_url)
        self.assertEqual(["https://www.douyin.com/user/sec_uid_abc"], client.urls)

    async def test_profile_url_resolution_extracts_same_sec_uid(self) -> None:
        gateway, client, _ = self._build()
        record = await gateway.resolve_identity(
            "https://www.douyin.com/user/sec_uid_abc?from=probe"
        )
        self.assertEqual("sec_uid_abc", record.sec_uid)
        self.assertEqual(["https://www.douyin.com/user/sec_uid_abc"], client.urls)

    async def test_invalid_identity_is_explicit_operation_failure(self) -> None:
        gateway, _, _ = self._build()
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.resolve_identity("https://live.douyin.com/1234567890")
        self.assertIs(ProviderFailureKind.UNKNOWN, ctx.exception.failure.kind)

    async def test_profile_maps_only_evidence_backed_fields(self) -> None:
        gateway, _, _ = self._build()
        profile = await gateway.fetch_profile("sec_uid_abc")
        self.assertEqual("Creator", profile.display_name)
        self.assertEqual(NOW, profile.observed_at)
        self.assertIsNone(profile.avatar_url)
        self.assertIsNone(profile.bio)

    async def test_live_record_preserves_raw_status_and_metadata(self) -> None:
        gateway, _, _ = self._build()
        live = await gateway.fetch_live("sec_uid_abc")
        self.assertEqual(2, live.raw_status)
        self.assertEqual("900", live.room_id)
        self.assertEqual("Live title", live.title)
        self.assertEqual(STREAMGET_DOUYIN_SOURCE, live.source)
        self.assertEqual(NOW, live.observed_at)

    async def test_start_time_is_only_parsed_from_explicit_positive_epoch(self) -> None:
        gateway, _, _ = self._build(
            {
                "status": 2,
                "start_time": "1787112000",
            }
        )
        live = await gateway.fetch_live("sec_uid_abc")
        self.assertIsNotNone(live.source_started_at)
        self.assertEqual(timezone.utc, live.source_started_at.tzinfo)

        for raw in (None, 0, -1, "bad", True):
            with self.subTest(raw=raw):
                gateway, _, _ = self._build({"status": 2, "start_time": raw})
                live = await gateway.fetch_live("sec_uid_abc")
                self.assertIsNone(live.source_started_at)

    async def test_timeout_and_network_exceptions_are_normalized(self) -> None:
        for error, expected in (
            (TimeoutError("timeout"), ProviderFailureKind.TIMEOUT),
            (ConnectionError("network"), ProviderFailureKind.NETWORK),
        ):
            with self.subTest(error=type(error).__name__):
                gateway, client, _ = self._build()
                client.error = error
                with self.assertRaises(ProviderOperationError) as ctx:
                    await gateway.fetch_live("sec_uid_abc")
                self.assertIs(expected, ctx.exception.failure.kind)

    async def test_generic_runtime_failure_stays_unknown_diagnostic(self) -> None:
        gateway, client, _ = self._build()
        client.error = RuntimeError("provider wrapper failure")
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("sec_uid_abc")
        self.assertIs(ProviderFailureKind.UNKNOWN, ctx.exception.failure.kind)

    async def test_explicit_response_identity_mismatch_is_ambiguous(self) -> None:
        gateway, _, _ = self._build(
            {
                "status": 2,
                "sec_uid": "other_identity",
            }
        )
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("sec_uid_abc")
        self.assertIs(ProviderFailureKind.AMBIGUOUS, ctx.exception.failure.kind)

    def test_gateway_is_lazy_and_has_no_legacy_runtime_dependency(self) -> None:
        source = GATEWAY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GATEWAY_PATH))
        forbidden = ("platform_adapters", "experiments", "core", "api", "workers")
        violations: list[str] = []
        top_level_streamget_imports: list[int] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
                if module == "streamget" and isinstance(getattr(node, "parent", None), ast.Module):
                    top_level_streamget_imports.append(node.lineno)

        self.assertEqual([], violations)
        # A source-level guard is clearer than relying on AST parent annotations:
        self.assertNotIn("\nfrom streamget import", source)
        self.assertNotIn("\nimport streamget", source)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)


if __name__ == "__main__":
    unittest.main()
