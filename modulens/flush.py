"""Flush orchestration: shape report, fan out to configured sinks."""
from __future__ import annotations

from typing import Any, Dict

from .config import config
from .report import build_ingest_payload, build_report
from .sinks import file as file_sink
from .sinks import http as http_sink


def flush_data(payload: Dict[str, Any], report: bool = True) -> bool:
    """
    Flush profiler data to file and/or Modulens ingest API.
    Returns True if all requested outputs succeeded (so profiler may reset state).
    """
    new_report = build_report(payload)
    output = (config.get("output") or "file").lower()
    file_ok = True
    http_ok = True

    if output in ("file", "both"):
        file_ok = file_sink.write(new_report)

    if output in ("http", "both"):
        http_ok = http_sink.send(build_ingest_payload(new_report))

    if output == "file":
        return file_ok
    if output == "http":
        return http_ok
    return file_ok and http_ok
