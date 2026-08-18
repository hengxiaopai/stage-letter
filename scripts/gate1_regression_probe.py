#!/usr/bin/env python3
"""Gate 1.1-6 regression probe against accepted Gate 0 oracle suites.

This script does not import experiments/* into formal runtime code. It executes
accepted deterministic Gate 0 test suites in isolated subprocess working
directories, then executes the formal Gate 1 contract suite.

It intentionally does NOT repeat real provider/WeChat sends or Gate 0A real
lifecycle evidence. Those remain accepted historical evidence with the inherited
Gate 0A DEGRADED lifecycle gap.
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
    Suite("Gate 1 formal contracts", ROOT, "tests/gate1", 55),
)


def _run_suite(suite: Suite) -> tuple[bool, int | None, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

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
        env=env,
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


def main() -> int:
    print("Gate 1.1-6 deterministic regression probe")
    print(f"python: {sys.executable}")

    failures: list[str] = []
    for suite in SUITES:
        ok, count, output = _run_suite(suite)
        if ok:
            print(f"PASS: {suite.name} -> {count} tests")
            continue

        failures.append(suite.name)
        print(
            f"FAIL: {suite.name} -> tests={count!r}, "
            f"minimum={suite.minimum_tests}"
        )
        print("----- suite output -----")
        print(output.rstrip())
        print("----- end suite output -----")

    if failures:
        print("FAIL: Gate 1.1-6 regression probe")
        print("failed suites:", ", ".join(failures))
        return 1

    print("PASS: Gate 0B/0C/0D/0E deterministic oracles remain green")
    print("PASS: Gate 1 formal contracts remain green")
    print("PASS: Gate 1.1-6 deterministic regression probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
