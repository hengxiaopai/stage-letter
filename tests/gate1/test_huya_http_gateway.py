from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.infrastructure.platforms.failures import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderOperationError,
)
from stage_letter.infrastructure.platforms.huya_http import (
    HUYA_HTML_SOURCE,
    HuyaHttpGateway,
)


ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "huya_http.py"
NOW = datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)


class _Transport:
    def __init__(self, html: str | None = None) -> None:
        self.html = html or '<html><body class="liveStatus-on"><script>{"eLiveStatus":2}</script></body></html>'
        self.urls: list[str] = []
        self.error: BaseException | None = None

    async def get_text(self, url: str) -> str:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.html


class HuyaHttpGatewayContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self, html: str | None = None) -> tuple[HuyaHttpGateway, _Transport]:
        transport = _Transport(html)
        gateway = HuyaHttpGateway(transport=transport, clock=lambda: NOW)
        return gateway, transport

    def test_parse_identity_accepts_numeric_desktop_and_mobile_room(self) -> None:
        gateway, _ = self._build()
        self.assertEqual("998", gateway.parse_identity("998"))
        self.assertEqual("998", gateway.parse_identity("https://www.huya.com/998"))
        self.assertEqual("998", gateway.parse_identity("https://m.huya.com/998?from=probe"))

    def test_invalid_identity_is_explicit_failure(self) -> None:
        gateway, _ = self._build()
        for value in ("", "0", "https://example.invalid/998", "huya-room"):
            with self.subTest(value=value):
                with self.assertRaises(ProviderOperationError):
                    gateway.parse_identity(value)

    async def test_resolution_uses_room_as_available_stable_monitor_identity(self) -> None:
        gateway, _ = self._build()
        record = await gateway.resolve_identity("https://www.huya.com/998")
        self.assertEqual("998", record.room_id)
        self.assertEqual("https://www.huya.com/998", record.canonical_url)

    async def test_e_live_status_2_is_preserved_as_raw_live_evidence(self) -> None:
        gateway, transport = self._build('<body><script>{"eLiveStatus":2}</script></body>')
        record = await gateway.fetch_live("998")
        self.assertEqual(2, record.raw_live_status)
        self.assertEqual(HUYA_HTML_SOURCE, record.source)
        self.assertEqual(["https://m.huya.com/998"], transport.urls)

    async def test_e_live_status_1_is_preserved_as_raw_offline_evidence(self) -> None:
        gateway, _ = self._build('<body><script>{"eLiveStatus":1}</script></body>')
        record = await gateway.fetch_live("998")
        self.assertEqual(1, record.raw_live_status)

    async def test_body_class_is_allowed_only_as_explicit_cross_signal_fallback(self) -> None:
        for html, expected in (
            ('<html><body class="x liveStatus-on y"></body></html>', "liveStatus-on"),
            ('<html><body class="liveStatus-off"></body></html>', "liveStatus-off"),
        ):
            with self.subTest(expected=expected):
                gateway, _ = self._build(html)
                record = await gateway.fetch_live("998")
                self.assertEqual(expected, record.raw_live_status)

    async def test_body_and_e_live_status_conflict_is_ambiguous(self) -> None:
        gateway, _ = self._build(
            '<html><body class="liveStatus-off"><script>{"eLiveStatus":2}</script></body></html>'
        )
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("998")
        self.assertIs(ProviderFailureKind.AMBIGUOUS, ctx.exception.failure.kind)

    async def test_unknown_numeric_status_is_preserved_not_guessed(self) -> None:
        gateway, _ = self._build('<body><script>{"eLiveStatus":3}</script></body>')
        record = await gateway.fetch_live("998")
        self.assertEqual(3, record.raw_live_status)

    async def test_missing_status_and_transport_failure_are_not_offline_truth(self) -> None:
        gateway, _ = self._build("<html><body>no status</body></html>")
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("998")
        self.assertIs(ProviderFailureKind.SCHEMA_DRIFT, ctx.exception.failure.kind)

        gateway, transport = self._build()
        transport.error = ProviderOperationError(
            ProviderFailure(ProviderFailureKind.TIMEOUT, "huya.http")
        )
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("998")
        self.assertIs(ProviderFailureKind.TIMEOUT, ctx.exception.failure.kind)

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
