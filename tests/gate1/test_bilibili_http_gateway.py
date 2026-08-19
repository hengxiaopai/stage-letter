from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stage_letter.infrastructure.platforms.bilibili_http import (
    BILIBILI_ROOM_SOURCE,
    BILIBILI_UID_SOURCE,
    BilibiliHttpGateway,
)
from stage_letter.infrastructure.platforms.failures import (
    ProviderFailureKind,
    ProviderOperationError,
)


ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = ROOT / "stage_letter" / "infrastructure" / "platforms" / "bilibili_http.py"
NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        # Current getRoomInfoOld shape is keyed by requested mid and does not
        # require uid to be echoed in the data object. Its status fields are
        # camelCase; formal transport must not treat missing uid as schema drift.
        self.uid_payload: dict[str, object] = {
            "code": 0,
            "data": {
                "roomStatus": 1,
                "roundStatus": 0,
                "liveStatus": 0,
                "roomid": 8758725,
                "title": "Room title",
            },
        }
        self.room_payload: dict[str, object] = {
            "code": 0,
            "data": {
                "uid": 528738158,
                "room_id": 8758725,
                "live_status": 0,
                "title": "Room title",
                "live_time": 0,
            },
        }

    async def get_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append((path, params))
        if path.endswith("getRoomInfoOld"):
            return self.uid_payload
        return self.room_payload


class BilibiliHttpGatewayContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[BilibiliHttpGateway, _Transport]:
        transport = _Transport()
        gateway = BilibiliHttpGateway(transport=transport, clock=lambda: NOW)
        return gateway, transport

    def test_parse_identity_accepts_uid_space_and_live_room(self) -> None:
        gateway, _ = self._build()
        self.assertEqual(("uid", "528738158"), gateway.parse_identity("528738158"))
        self.assertEqual(
            ("uid", "528738158"),
            gateway.parse_identity("https://space.bilibili.com/528738158"),
        )
        self.assertEqual(
            ("room", "8758725"),
            gateway.parse_identity("https://live.bilibili.com/8758725"),
        )

    def test_invalid_identity_is_explicit_failure(self) -> None:
        gateway, _ = self._build()
        with self.assertRaises(ProviderOperationError):
            gateway.parse_identity("https://example.invalid/not-bilibili")

    async def test_uid_resolution_uses_requested_uid_when_endpoint_omits_uid(self) -> None:
        gateway, transport = self._build()
        record = await gateway.resolve_identity("528738158")
        self.assertEqual("528738158", record.uid)
        self.assertEqual("8758725", record.room_id)
        self.assertEqual("https://space.bilibili.com/528738158", record.canonical_url)
        self.assertEqual(BILIBILI_UID_SOURCE, "bilibili.getRoomInfoOld")
        self.assertTrue(transport.calls[0][0].endswith("getRoomInfoOld"))

    async def test_room_resolution_converts_room_to_stable_uid(self) -> None:
        gateway, transport = self._build()
        record = await gateway.resolve_identity("https://live.bilibili.com/8758725")
        self.assertEqual("528738158", record.uid)
        self.assertEqual("8758725", record.room_id)
        self.assertEqual(BILIBILI_ROOM_SOURCE, "bilibili.room_init")
        self.assertTrue(transport.calls[0][0].endswith("room_init"))

    async def test_fetch_live_reads_current_camelcase_status_and_carousel(self) -> None:
        gateway, transport = self._build()
        transport.uid_payload["data"] = {
            "roomStatus": 1,
            "roundStatus": 0,
            "liveStatus": 1,
            "roomid": 8758725,
            "title": "Live title",
        }
        record = await gateway.fetch_live("528738158")
        self.assertEqual(1, record.raw_live_status)
        self.assertEqual("8758725", record.room_id)
        self.assertEqual("Live title", record.title)
        self.assertEqual(NOW, record.observed_at)

        transport.uid_payload["data"] = {
            "roomStatus": 1,
            "roundStatus": 1,
            "liveStatus": 0,
            "roomid": 8758725,
        }
        carousel = await gateway.fetch_live("528738158")
        self.assertEqual(2, carousel.raw_live_status)

    async def test_legacy_snake_case_status_and_live_time_remain_supported(self) -> None:
        gateway, transport = self._build()
        transport.uid_payload["data"] = {
            "roomid": 8758725,
            "live_status": 1,
            "title": "Live title",
            "live_time": 1787112000,
        }
        record = await gateway.fetch_live("528738158")
        self.assertEqual(1, record.raw_live_status)
        self.assertIsNotNone(record.source_started_at)

    async def test_nonzero_provider_code_is_not_offline_truth(self) -> None:
        gateway, transport = self._build()
        transport.uid_payload = {"code": 1, "msg": "not found", "data": None}
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("528738158")
        self.assertIs(ProviderFailureKind.NOT_FOUND, ctx.exception.failure.kind)

    async def test_explicit_provider_uid_mismatch_is_ambiguous(self) -> None:
        gateway, transport = self._build()
        transport.uid_payload["data"] = {
            "uid": 999,
            "roomid": 8758725,
            "liveStatus": 1,
        }
        with self.assertRaises(ProviderOperationError) as ctx:
            await gateway.fetch_live("528738158")
        self.assertIs(ProviderFailureKind.AMBIGUOUS, ctx.exception.failure.kind)

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
