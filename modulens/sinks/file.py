"""Local JSON report sink with size + count rotation."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ..config import config
from ..constants import (
    DEFAULT_RUNTIME_REPORT_PATH,
    FILE_REPORT_TRIM_DIVISOR,
    LOCAL_REPORT_JSON_INDENT,
    MAX_FILE_REPORTS,
    MAX_FILE_SIZE_BYTES,
)


def output_path() -> str:
    configured = (config.get("output_path") or "").strip()
    return configured or DEFAULT_RUNTIME_REPORT_PATH


def _load_existing(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE_BYTES:
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        if len(data) > MAX_FILE_REPORTS:
            return data[-MAX_FILE_REPORTS // FILE_REPORT_TRIM_DIVISOR :]
        return data
    except Exception:
        return []


def write(new_report: Dict[str, Any]) -> bool:
    """Append a report to the configured local JSON file. Returns True on success."""
    path = output_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        reports = _load_existing(path)
        reports.append(new_report)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reports, f, indent=LOCAL_REPORT_JSON_INDENT)
        return True
    except Exception:
        return False
