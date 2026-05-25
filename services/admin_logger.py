"""Structured JSON-line logging for the admin log auditor."""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from typing import Any

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
_LOG_PATH = os.path.join(_LOG_DIR, "system.log")

os.makedirs(_LOG_DIR, exist_ok=True)


def _write(level: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "message": message,
        "context": context or {},
    }
    with open(_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def log_info(message: str, **context: Any) -> dict[str, Any]:
    return _write("INFO", message, context)


def log_warn(message: str, **context: Any) -> dict[str, Any]:
    return _write("WARN", message, context)


def log_error(message: str, *, exc: BaseException | None = None, **context: Any) -> dict[str, Any]:
    if exc is not None:
        context = {
            **context,
            "stack_trace": traceback.format_exc(),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
    return _write("ERROR", message, context)


def read_logs(
    *,
    search: str = "",
    severity: str = "all",
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    if not os.path.isfile(_LOG_PATH):
        return [], 0
    entries: list[dict[str, Any]] = []
    with open(_LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            level = str(entry.get("level", "INFO")).upper()
            if severity == "error" and level != "ERROR":
                continue
            if severity == "warn" and level != "WARN":
                continue
            if search:
                blob = json.dumps(entry, ensure_ascii=False).lower()
                if search.lower() not in blob:
                    continue
            entries.append(entry)
    total = len(entries)
    entries.reverse()
    return entries[offset : offset + limit], total
