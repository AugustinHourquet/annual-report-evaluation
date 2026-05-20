"""Cross-platform dev helpers invoked by the Makefile.

This script encapsulates the bits of the dev workflow that aren't portable
in plain shell (rm -rf, tail, grep), so the Makefile can run on
both Unix and Windows by delegating to Python.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_clean(_args: argparse.Namespace) -> None:
    """Remove build artefacts and caches, but keep the venv."""
    for d in ("build", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
        shutil.rmtree(d, ignore_errors=True)
    for pattern in ("*.egg-info", "__pycache__"):
        for p in Path(".").rglob(pattern):
            shutil.rmtree(p, ignore_errors=True)



def cmd_log_tail(_args: argparse.Namespace) -> None:
    """Print the last 20 lines of the run log, or a friendly message."""
    p = Path("logs/run_log.jsonl")
    if not p.exists():
        print("(no log yet)")
        return
    for line in p.read_text(encoding="utf-8").splitlines()[-20:]:
        print(line)


def cmd_log_failures(_args: argparse.Namespace) -> None:
    """Print every JSONL record whose status is 'failure'."""
    p = Path("logs/run_log.jsonl")
    if not p.exists():
        print("(no log yet)")
        return
    found = False
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status") == "failure":
            print(line)
            found = True
    if not found:
        print("(no failures)")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="dev.py")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    sub.add_parser("clean", help="Remove build artefacts and caches")
    sub.add_parser("log-tail", help="Show last 20 lines of logs/run_log.jsonl")
    sub.add_parser("log-failures", help="Show all failure entries from the run log")

    args = parser.parse_args()
    handlers = {
        "clean": cmd_clean,
        "log-tail": cmd_log_tail,
        "log-failures": cmd_log_failures,
    }
    handlers[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
