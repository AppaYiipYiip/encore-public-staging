"""Running ffmpeg and friends, with a time limit, never through a shell."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], int], RunResult]


def run_command(argv: list[str], timeout: int) -> RunResult:
    try:
        # UTF-8 on every machine: the Windows default would garble non-Latin titles.
        done = subprocess.run(  # noqa: S603 - argv is a list, never a shell string
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
        )
        return RunResult(done.returncode, done.stdout, done.stderr)
    except subprocess.TimeoutExpired:
        return RunResult(124, "", "timeout")
    except FileNotFoundError:
        return RunResult(127, "", "not installed")
