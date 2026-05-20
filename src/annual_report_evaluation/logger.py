"""Append-only JSONL run logger.

One line per evaluation run, written to `logs/run_log.jsonl`. The log is
never rewritten — only appended.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_run_log(log_path: str | Path, entry: dict[str, Any]) -> Path:
    """Append one JSON record to the run log, creating the file if needed.

    The function never raises on a missing parent directory — it will be
    created. The record is written atomically as a single line.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Make sure we always have a timestamp; callers can override.
    entry = {"ts": utcnow_iso(), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path
