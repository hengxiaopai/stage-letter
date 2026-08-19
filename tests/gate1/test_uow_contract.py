from __future__ import annotations

import ast
import unittest
from pathlib import Path

from stage_letter.application.ports import UnitOfWork
from stage_letter.infrastructure.db.uow import SQLAlchemyUnitOfWork


ROOT = Path(__file__).resolve().parents[2]
UOW_PATH = ROOT / "stage_letter" / "infrastructure" / "db" / "uow.py"


class _FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class UnitOfWorkContractTests(unittest.IsolatedAsyncioTestCase):
    def _build(self) -> tuple[SQLAlchemyUnitOfWork, _FakeSession]:
        session = _FakeSession()
        return SQLAlchemyUnitOfWork(lambda: session), session  # type: ignore[arg-type]

    async def test_concrete_uow_structurally_implements_port(self) -> None:
        uow, _ = self._build()
        self.assertIsInstance(uow, UnitOfWork)

    async def test_enter_binds_all_repositories_to_same_session(self) -> None:
        uow, session = self._build()
        async with uow:
            self.assertIs(uow.session, session)
            self.assertIs(uow.creators.session, session)  # type: ignore[union-attr]
            self.assertIs(uow.follows.session, session)  # type: ignore[union-attr]
            self.assertIs(uow.live.session, session)  # type: ignore[union-attr]
            self.assertIs(uow.notifications.session, session)  # type: ignore[union-attr]

    async def test_explicit_commit_delegates_once_and_normal_exit_does_not_rollback(self) -> None:
        uow, session = self._build()
        async with uow:
            await uow.commit()
        self.assertEqual(1, session.commit_calls)
        self.assertEqual(0, session.rollback_calls)
        self.assertEqual(1, session.close_calls)

    async def test_normal_exit_without_commit_rolls_back(self) -> None:
        uow, session = self._build()
        async with uow:
            pass
        self.assertEqual(0, session.commit_calls)
        self.assertEqual(1, session.rollback_calls)
        self.assertEqual(1, session.close_calls)

    async def test_exceptional_exit_rolls_back_and_propagates_exception(self) -> None:
        uow, session = self._build()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            async with uow:
                raise RuntimeError("boom")
        self.assertEqual(0, session.commit_calls)
        self.assertEqual(1, session.rollback_calls)
        self.assertEqual(1, session.close_calls)

    async def test_explicit_rollback_delegates_and_exit_remains_safe(self) -> None:
        uow, session = self._build()
        async with uow:
            await uow.rollback()
        self.assertEqual(0, session.commit_calls)
        self.assertEqual(2, session.rollback_calls)
        self.assertEqual(1, session.close_calls)

    async def test_commit_and_rollback_require_active_context(self) -> None:
        uow, _ = self._build()
        with self.assertRaises(RuntimeError):
            await uow.commit()
        with self.assertRaises(RuntimeError):
            await uow.rollback()

    async def test_nested_reentry_is_rejected(self) -> None:
        uow, _ = self._build()
        async with uow:
            with self.assertRaises(RuntimeError):
                await uow.__aenter__()

    async def test_uow_does_not_import_transport_provider_or_legacy_runtime(self) -> None:
        tree = ast.parse(UOW_PATH.read_text(encoding="utf-8"), filename=str(UOW_PATH))
        forbidden = ("api", "workers", "core", "platform_adapters", "experiments", "requests", "httpx")
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


if __name__ == "__main__":
    unittest.main()
