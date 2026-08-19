#!/usr/bin/env python3
"""Gate 1 deterministic boundary regression probe.

This probe re-runs the accepted deterministic Gate 0B-0E oracle suites and the
entire formal Gate 1 contract suite, then verifies the current Alembic head and
UTF-8 offline SQL compilation. It deliberately does not perform provider/network
calls, real WeChat sends, or repeat the deferred Gate 0A lifecycle experiment.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAN_RE = re.compile(r"Ran\s+(\d+)\s+tests?")
EXPECTED_HEAD = "d14e7c9a5b30"


@dataclass(frozen=True)
class Suite:
    name: str
    cwd: Path
    start_dir: str
    minimum_tests: int


SUITES = (
    Suite("Gate 0B state/persistence oracle", ROOT / "experiments/gate0b", ".", 37),
    Suite("Gate 0C health/composition oracle", ROOT / "experiments/gate0c", ".", 65),
    Suite("Gate 0D notification/delivery oracle", ROOT / "experiments/gate0d", ".", 54),
    Suite("Gate 0E golden path oracle", ROOT / "experiments/gate0e", ".", 15),
    Suite("Gate 1 formal contracts", ROOT, "tests/gate1", 111),
)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_suite(suite: Suite) -> tuple[bool, int | None, str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            suite.start_dir,
            "-p",
            "test_*.py",
            "-v",
        ],
        cwd=suite.cwd,
        env=_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    match = RAN_RE.search(combined)
    count = int(match.group(1)) if match else None
    ok = completed.returncode == 0 and count is not None and count >= suite.minimum_tests
    return ok, count, combined


def _run_command(args: list[str]) -> tuple[bool, str]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    return completed.returncode == 0, combined


def main() -> int:
    print("Gate 1 deterministic boundary regression probe")
    print(f"python: {sys.executable}")

    failures: list[str] = []
    for suite in SUITES:
        ok, count, output = _run_suite(suite)
        if ok:
            print(f"PASS: {suite.name} -> {count} tests")
            continue
        failures.append(suite.name)
        print(f"FAIL: {suite.name} -> tests={count!r}, minimum={suite.minimum_tests}")
        print("----- suite output -----")
        print(output.rstrip())
        print("----- end suite output -----")

    head_ok, head_output = _run_command([sys.executable, "-m", "alembic", "heads"])
    head_text = head_output.strip()
    if head_ok and f"{EXPECTED_HEAD} (head)" in head_text:
        print(f"PASS: Alembic head -> {EXPECTED_HEAD}")
    else:
        failures.append("Alembic head")
        print(f"FAIL: Alembic head expected {EXPECTED_HEAD!r}")
        print(head_text)

    sql_ok, sql_output = _run_command(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"]
    )
    if sql_ok:
        print("PASS: UTF-8 offline SQL compilation through current Gate 1 head")
    else:
        failures.append("offline SQL compilation")
        print("FAIL: UTF-8 offline SQL compilation")
        print(sql_output.rstrip())

    if failures:
        print("FAIL: Gate 1 deterministic boundary regression probe")
        print("failed checks:", ", ".join(failures))
        return 1

    print("PASS: Gate 0B/0C/0D/0E deterministic oracles remain green")
    print("PASS: Gate 1 formal contracts remain green")
    print("PASS: current Gate 1 schema head/offline SQL remain green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
