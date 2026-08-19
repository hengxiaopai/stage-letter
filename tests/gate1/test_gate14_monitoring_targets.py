from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from stage_letter.application.errors import ApplicationInvariantError
from stage_letter.application.services.monitoring import MonitoringTargetApplicationService
from stage_letter.domain.creators import PlatformAccount
from stage_letter.infrastructure.db.repositories.creator import SQLAlchemyCreatorRepository
from workers.composition import build_worker_services


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "stage_letter" / "application" / "services" / "monitoring.py"
REPOSITORY_PATH = ROOT / "stage_letter" / "infrastructure" / "db" / "repositories" / "creator.py"


def _account(account_id: str, *, enabled: bool = True) -> PlatformAccount:
    return PlatformAccount(
        account_id=account_id,
        creator_id=account_id,
        platform="douyin",
        platform_user_id=f"sec-{account_id}",
        enabled=enabled,
    )


class _Creators:
    def __init__(self, accounts: tuple[PlatformAccount, ...]) -> None:
        self.accounts = accounts
        self.calls: list[tuple[str | None, int]] = []

    async def list_enabled_accounts(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformAccount, ...]:
        self.calls.append((after_account_id, limit))
        return self.accounts


class _Uow:
    def __init__(self, creators: _Creators) -> None:
        self.creators = creators
        self.enter_count = 0
        self.commit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class Gate14MonitoringTargetContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_page_is_read_only_and_returns_repository_targets(self) -> None:
        creators = _Creators((_account("1"), _account("2")))
        uow = _Uow(creators)
        service = MonitoringTargetApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.list_targets()

        self.assertEqual(("1", "2"), tuple(item.account_id for item in result))
        self.assertEqual([(None, 100)], creators.calls)
        self.assertEqual(1, uow.enter_count)
        self.assertEqual(0, uow.commit_count)

    async def test_cursor_and_limit_are_forwarded_without_provider_work(self) -> None:
        creators = _Creators((_account("11"),))
        uow = _Uow(creators)
        service = MonitoringTargetApplicationService(lambda: uow)  # type: ignore[arg-type]

        result = await service.list_targets(after_account_id="10", limit=25)

        self.assertEqual(("11",), tuple(item.account_id for item in result))
        self.assertEqual([("10", 25)], creators.calls)

    async def test_zero_page_size_is_rejected_before_opening_uow(self) -> None:
        creators = _Creators(())
        uow = _Uow(creators)
        service = MonitoringTargetApplicationService(lambda: uow)  # type: ignore[arg-type]

        with self.assertRaises(ApplicationInvariantError):
            await service.list_targets(limit=0)
        self.assertEqual(0, uow.enter_count)

    async def test_page_size_above_hard_cap_is_rejected_before_opening_uow(self) -> None:
        creators = _Creators(())
        uow = _Uow(creators)
        service = MonitoringTargetApplicationService(lambda: uow)  # type: ignore[arg-type]

        with self.assertRaises(ApplicationInvariantError):
            await service.list_targets(limit=1001)
        self.assertEqual(0, uow.enter_count)

    def test_creator_repository_exposes_async_monitoring_target_query(self) -> None:
        method = SQLAlchemyCreatorRepository.list_enabled_accounts
        self.assertTrue(inspect.iscoroutinefunction(method))
        parameters = inspect.signature(method).parameters
        self.assertIn("after_account_id", parameters)
        self.assertIn("limit", parameters)

    def test_sql_target_query_is_explicit_enabled_keyset_paging(self) -> None:
        source = REPOSITORY_PATH.read_text(encoding="utf-8")
        self.assertIn("PlatformAccountModel.is_disabled.is_(False)", source)
        self.assertIn("PlatformAccountModel.id > after_pk", source)
        self.assertIn("order_by(PlatformAccountModel.id.asc()).limit(limit)", source)
        self.assertNotIn("NotificationPreferenceModel", source)

    def test_monitoring_target_service_is_infrastructure_and_provider_free(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SERVICE_PATH))
        forbidden = (
            "stage_letter.infrastructure",
            "platform_adapters",
            "experiments",
            "workers",
            "api",
            "sqlalchemy",
            "httpx",
            "requests",
            "streamget",
        )
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
        self.assertNotIn("Notification", source)

    def test_worker_bundle_construction_does_not_open_database_or_provider_io(self) -> None:
        calls = 0

        def session_factory():
            nonlocal calls
            calls += 1
            return object()

        bundle = build_worker_services(session_factory)  # type: ignore[arg-type]
        self.assertIsInstance(bundle.monitoring_targets, MonitoringTargetApplicationService)
        self.assertEqual(0, calls)


if __name__ == "__main__":
    unittest.main()
