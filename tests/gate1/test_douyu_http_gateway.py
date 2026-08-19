from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.infrastructure.platforms.douyu_http import (
    DOUYU_HTML_SOURCE,
    DouyuHttpGateway,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "douyu_http.py"
NOW = datetime(2026, 8, 19, 7, 10, tzinfo=timezone.utc)


class _Transport:
    def __init__(self, html: str | None = None) -> None:
        self.html = html or '<html><script>{\\"show_status\\":1}</script></html>'
        self.calls: list[str] = []

    async def get_text(self, url: str) -> str:
        self.calls.append(url)
        return self.html


class DouyuHttpGatewayContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self, html: str | None = None) -> tuple[DouyuHttpGateway, _Transport]:
        transport = _Transport(html)
        gateway = DouyuHttpGateway(transport=transport, clock=lambda: NOW)
        return gateway, transport

    def test_parse_identity_accepts_room_id_and_url(self) -> None:
        gateway, _ = self._build()
        self.assertEqual("9999", gateway.parse_identity("9999"))
        self.assertEqual("9999", gateway.parse_identity("https://www.douyu.com/9999"))
        self.assertEqual("9999", gateway.parse_identity("https://douyu.com/9999?foo=bar"))

    def test_invalid_identity_is_explicit_failure(self) -> None:
        gateway, _ = self._build()
        with self.assertRaises(ProviderOperationError):
            gateway.parse_identity("https://example.invalid/9999")

    async def test_resolve_identity_uses_room_as_stable_key(self) -> None:
        gateway, _ = self._build()
        record = await gateway.resolve_identity("https://www.douyu.com/9999")
        self.assertEqual("9999", record.room_id)
        self.assertEqual("https://www.douyu.com/9999", record.canonical_url)

    async def test_fetch_live_parses_escaped_show_status_1(self) -> None:
        gateway, transport = self._build('<script>{\\"show_status\\":1}</script>')
        record = await gateway.fetch_live("9999")
        self.assertEqual(1, record.raw_live_status)
        self.assertEqual(DOUYU_HTML_SOURCE, record.source)
        self.assertEqual(NOW, record.observed_at)
        self.assertEqual("https://www.douyu.com/9999", transport.calls[0])

    async def test_fetch_live_parses_show_status_2(self) -> None:
        gateway, _ = self._build('<script>{"show_status":2}</script>')
        record = await gateway.fetch_live("9999")
        self.assertEqual(2, record.raw_live_status)

    async def test_ambiguous_values_are_preserved_raw_not_guessed(self) -> None:
        gateway, transport = self._build()
        for raw in (0, 3, 4):
            with self.subTest(raw=raw):
                transport.html = f'<script>{{"show_status":{raw}}}</script>'
                record = await gateway.fetch_live("9999")
                self.assertEqual(raw, record.raw_live_status)

    async def test_video_loop_without_show_status_is_not_creator_live_truth(self) -> None:
        gateway, _ = self._build('<script>{"videoLoop":1}</script>')
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("9999")
        self.assertIs(ProviderFailureKind.SCHEMA_DRIFT, ctx.exception.failure.kind)

    async def test_conflicting_show_status_fields_are_ambiguous(self) -> None:
        gateway, _ = self._build('<script>{"show_status":1,"showStatus":2}</script>')
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("9999")
        self.assertIs(ProviderFailureKind.AMBIGUOUS, ctx.exception.failure.kind)

    async def test_start_time_and_title_are_optional_metadata(self) -> None:
        gateway, _ = self._build(
            '<title>Room title</title><script>{"show_status":1,"roomStartTime":1787113200}</script>'
        )
        record = await gateway.fetch_live("9999")
        self.assertEqual("Room title", record.title)
        self.assertIsNotNone(record.source_started_at)

    def test_gateway_has_no_legacy_or_state_engine_dependency(self) -> None:
        source = GATEWAY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GATEWAY_PATH))
        forbidden = ("platform_adapters", "experiments", "core", "api", "workers")
        violations: list[str] = []
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            for module in modules:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{node.lineno}:{module}")
        self.assertEqual([], violations)
        self.assertNotIn("LiveSession", source)
        self.assertNotIn("LiveEvent", source)
        self.assertNotIn("commit(", source)


if __name__ == "__main__":
    unittest.main()
