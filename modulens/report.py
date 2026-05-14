"""Pure transformations from profiler output to the report / ingest payload shapes."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from .config import config
from .constants import (
    AVG_TIME_MS_DECIMALS,
    DEFAULT_ENVIRONMENT,
    MS_PER_SEC,
)


def build_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Shape the local-report dict from raw profiler payload."""
    new_report: Dict[str, Any] = {
        "timestamp": int(time.time()),
        "called_functions": {},
        "dead_functions": sorted(payload.get("dead_functions", [])),
    }
    error_counts = payload.get("error_counts", {})
    for func, stats in payload.get("called_functions", {}).items():
        count = stats.get("count", 0)
        total_time = stats.get("total_time_sec", 0.0)
        avg_time = (
            round(MS_PER_SEC * total_time / count, AVG_TIME_MS_DECIMALS) if count else 0.0
        )
        new_report["called_functions"][func] = {
            "count": count,
            "avg_time_ms": avg_time,
            "error_count": error_counts.get(func, 0),
        }
    feature_flags: List[Dict[str, Any]] = payload.get("feature_flags") or []
    if feature_flags:
        new_report["feature_flags"] = feature_flags
    return new_report


def build_ingest_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    """Shape the backend SnapshotInput payload from a finished report dict."""
    payload: Dict[str, Any] = {
        "timestamp": report["timestamp"],
        "environment": config.get("environment", DEFAULT_ENVIRONMENT),
        "project_id": config.get("project_id", ""),
        "called_functions": report["called_functions"],
        "dead_functions": report["dead_functions"],
    }
    feature_flags = report.get("feature_flags") or []
    if feature_flags:
        payload["feature_flags"] = feature_flags
    return payload
