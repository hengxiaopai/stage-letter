from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from stage_letter.application.errors import ApplicationInvariantError, ApplicationNotFoundError
from stage_letter.application.services import (
    CreatorApplicationService,
    FollowApplicationService,
    LiveObservationApplicationService,
)
from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import LiveObservation, LiveStatus


ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = ROOT / "stage_letter" / "application" / "services"


class _FakeUoW:
    def __init__(self) -> None:
        self.creators = SimpleNamespace(
            get_account=AsyncMock(return_value=None),
            save_creator=AsyncMock(),
            save_profile=AsyncMock(),
            save_account=AsyncMock(),
        )
        self.follows = SimpleNamespace(
            get_notification_preference=AsyncMock(return_value=None),
            save_follow=AsyncMock(),
            delete_follow=AsyncMock(),
            save_notification_preference=AsyncMock(),
        )
        self.live = SimpleNamespace(append_observation=AsyncMock())
        self.notifications = SimpleNamespace()
        self.grants = SimpleNamespace()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


class ApplicationServiceContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_creator_bundle_persists_all_parts_then_commits(self) -> None:
        uow = _FakeUoW()
        service = CreatorApplicationService(lambda: uow)  # type: ignore[arg-type]
        creator = Creator("100")
        profile = CreatorProfile("100", display_name="Creator")
        account = PlatformAccount("200", "100", "douyin", "dy-200")

        await service.save_bundle(creator, profile=profile, account=account)

        uow.creators.save_creator.assert_awaited_once_with(creator)
        uow.creators.save_profile.assert_awaited_once_with(profile)
        uow.creators.save_account.assert_awaited_once_with(account)
        uow.commit.assert_awaited_once()

    async def test_creator_bundle_rejects_profile_identity_mismatch_before_uow(self) -> None:
        uow = _FakeUoW()
        service = CreatorApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.save_bundle(Creator("100"), profile=CreatorProfile("101"))
        self.assertEqual(0, uow.enter_calls)

    async def test_creator_bundle_rejects_account_identity_mismatch_before_uow(self) -> None:
        uow = _FakeUoW()
        service = CreatorApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationInvariantError):
            await service.save_bundle(
                Creator("100"),
                account=PlatformAccount("200", "101", "douyin", "dy-200"),
            )
        self.assertEqual(0, uow.enter_calls)

    async def test_follow_resolves_creator_from_platform_account_and_commits(self) -> None:
        uow = _FakeUoW()
        account = PlatformAccount("200", "100", "douyin", "dy-200")
        uow.creators.get_account.return_value = account
        service = FollowApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.follow_account(user_id="1", account_id="200", starred=True)

        expected = Follow("1", "100", "200", starred=True)
        self.assertEqual(expected, result)
        uow.follows.save_follow.assert_awaited_once_with(expected)
        uow.follows.get_notification_preference.assert_awaited_once_with("1", "200")
        uow.follows.save_notification_preference.assert_awaited_once_with(
            NotificationPreference("1", "200", enabled=True)
        )
        uow.commit.assert_awaited_once()

    async def test_follow_missing_account_fails_without_write_or_commit(self) -> None:
        uow = _FakeUoW()
        service = FollowApplicationService(lambda: uow)  # type: ignore[arg-type]
        with self.assertRaises(ApplicationNotFoundError):
            await service.follow_account(user_id="1", account_id="404")
        uow.follows.save_follow.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_notification_preference_is_saved_separately_from_follow(self) -> None:
        uow = _FakeUoW()
        uow.creators.get_account.return_value = PlatformAccount("200", "100", "douyin", "dy-200")
        service = FollowApplicationService(lambda: uow)  # type: ignore[arg-type]
        preference = NotificationPreference("1", "200", enabled=False)

        await service.set_notification_preference(preference)

        uow.follows.save_notification_preference.assert_awaited_once_with(preference)
        uow.follows.save_follow.assert_not_awaited()
        uow.commit.assert_awaited_once()

    async def test_unfollow_does_not_implicitly_rewrite_notification_preference(self) -> None:
        uow = _FakeUoW()
        service = FollowApplicationService(lambda: uow)  # type: ignore[arg-type]

        await service.unfollow_account(user_id="1", account_id="200")

        uow.follows.delete_follow.assert_awaited_once_with("1", "200")
        uow.follows.save_notification_preference.assert_not_awaited()
        uow.commit.assert_awaited_once()

    async def test_live_observation_records_normalized_fact_and_commits(self) -> None:
        uow = _FakeUoW()
        uow.creators.get_account.return_value = PlatformAccount("200", "100", "douyin", "dy-200")
        service = LiveObservationApplicationService(lambda: uow)  # type: ignore[arg-type]
        observation = LiveObservation(
            observation_id="obs:1",
            account_id="200",
            status=LiveStatus.UNKNOWN,
            observed_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            source="gate12-service-test",
        )

        await service.record(observation)

        uow.live.append_observation.assert_awaited_once_with(observation)
        uow.commit.assert_awaited_once()

    async def test_live_observation_missing_account_fails_without_write_or_commit(self) -> None:
        uow = _FakeUoW()
        service = LiveObservationApplicationService(lambda: uow)  # type: ignore[arg-type]
        observation = LiveObservation(
            observation_id="obs:missing",
            account_id="404",
            status=LiveStatus.LIVE,
            observed_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
            source="gate12-service-test",
        )
        with self.assertRaises(ApplicationNotFoundError):
            await service.record(observation)
        uow.live.append_observation.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_application_services_remain_infrastructure_free_and_do_not_own_state_engine(self) -> None:
        forbidden = (
            "stage_letter.infrastructure",
            "api",
            "workers",
            "core",
            "platform_adapters",
            "experiments",
            "sqlalchemy",
            "alembic",
            "asyncpg",
            "fastapi",
            "redis",
            "dramatiq",
            "requests",
            "httpx",
        )
        violations: list[str] = []
        for path in SERVICES_ROOT.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                for module in modules:
                    if any(module == p or module.startswith(p + ".") for p in forbidden):
                        violations.append(f"{path.name}:{node.lineno}:{module}")
            if path.name == "live.py":
                self.assertNotIn("LiveSession", source)
                self.assertNotIn("LiveEvent", source)
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
