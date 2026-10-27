"""Bounded subprocess helpers; collected values are always treated as data."""

from __future__ import annotations

import shutil
import os
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Command:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: str | None = None


def run(args: Sequence[str], timeout: float = 8, *, env: dict[str, str] | None = None) -> Command:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
                              env=dict(os.environ, LC_ALL="C", LANG="C", **(env or {})))
        return Command(proc.stdout, proc.stderr, proc.returncode)
    except FileNotFoundError:
        return Command(error=f"Required command not found: {args[0]}")
    except subprocess.TimeoutExpired:
        return Command(error=f"Command timed out after {timeout:g}s: {args[0]}")
    except OSError as exc:
        return Command(error=f"Could not run {args[0]}: {exc}")


def find_executable(name: str) -> str | None:
    return shutil.which(name)
