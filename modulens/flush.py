import os
import json
import time
import urllib.request
import urllib.error

from .config import config
from .constants import (
    AVG_TIME_MS_DECIMALS,
    DEFAULT_RUNTIME_REPORT_PATH,
    FILE_REPORT_TRIM_DIVISOR,
    HTTP_CLIENT_ERROR_MAX_EXCLUSIVE,
    HTTP_CLIENT_ERROR_MIN,
    HTTP_REQUEST_TIMEOUT_SEC,
    HTTP_RETRY_DELAY_SEC,
    HTTP_SUCCESS_STATUS_MAX_EXCLUSIVE,
    HTTP_SUCCESS_STATUS_MIN,
    HTTP_TOO_MANY_REQUESTS,
    INGEST_ENDPOINT,
    LOCAL_REPORT_JSON_INDENT,
    MAX_FILE_REPORTS,
    MAX_FILE_SIZE_BYTES,
    MAX_HTTP_RETRIES,
    MS_PER_SEC,
)


def _build_report(payload: dict) -> dict:
    """Build report dict (timestamp, called_functions, dead_functions) from profiler payload."""
    new_report = {
        "timestamp": int(time.time()),
        "called_functions": {},
        "dead_functions": sorted(payload.get("dead_functions", [])),
    }
    error_counts = payload.get("error_counts", {})
    for func, stats in payload.get("called_functions", {}).items():
        count = stats.get("count", 0)
        total_time = stats.get("total_time_sec", 0.0)
        avg_time = round(MS_PER_SEC * total_time / count, AVG_TIME_MS_DECIMALS) if count else 0.0
        new_report["called_functions"][func] = {
            "count": count,
            "avg_time_ms": avg_time,
            "error_count": error_counts.get(func, 0),
        }
    feature_flags = payload.get("feature_flags") or []
    if feature_flags:
        new_report["feature_flags"] = feature_flags
    return new_report


def _build_ingest_payload(report: dict) -> dict:
    """Build backend SnapshotInput payload (project_id, environment, etc.)."""
    payload = {
        "timestamp": report["timestamp"],
        "environment": config.get("environment", "production"),
        "project_id": config.get("project_id", ""),
        "called_functions": report["called_functions"],
        "dead_functions": report["dead_functions"],
    }
    feature_flags = report.get("feature_flags") or []
    if feature_flags:
        payload["feature_flags"] = feature_flags
    return payload


def _send_ingest(payload: dict, report: bool) -> bool:
    """POST payload to Modulens ingest API. Returns True on success."""
    api_url = (config.get("api_url") or "").strip()
    api_key = (config.get("api_key") or "").strip()
    project_id = (config.get("project_id") or "").strip()
    if not api_url or not api_key or not project_id:
        return True  # not a failure, just skipped

    url = f"{api_url.rstrip('/')}{INGEST_ENDPOINT}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )

    last_error = None
    for attempt in range(MAX_HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT_SEC) as resp:
                if HTTP_SUCCESS_STATUS_MIN <= resp.status < HTTP_SUCCESS_STATUS_MAX_EXCLUSIVE:
                    return True
                last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if (
                e.code
                and HTTP_CLIENT_ERROR_MIN <= e.code < HTTP_CLIENT_ERROR_MAX_EXCLUSIVE
                and e.code != HTTP_TOO_MANY_REQUESTS
            ):
                break  # no retry on client errors
        except urllib.error.URLError as e:
            last_error = str(e.reason or e)
        except Exception as e:
            last_error = str(e)
        if attempt < MAX_HTTP_RETRIES:
            time.sleep(HTTP_RETRY_DELAY_SEC * (attempt + 1))

    return False


def _output_path() -> str:
    configured = (config.get("output_path") or "").strip()
    return configured or DEFAULT_RUNTIME_REPORT_PATH


def flush_data(payload: dict, report: bool = True) -> bool:
    """
    Flush profiler data to file and/or Modulens ingest API.
    Returns True if all requested outputs succeeded (so profiler may reset state).
    """
    new_report = _build_report(payload)
    output = (config.get("output") or "file").lower()
    file_ok = True
    http_ok = True

    if output in ("file", "both"):
        output_path = _output_path()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        if os.path.exists(output_path):
            try:
                file_size = os.path.getsize(output_path)
                if file_size > MAX_FILE_SIZE_BYTES:
                    report_array = []
                else:
                    with open(output_path, "r") as f:
                        report_array = json.load(f)
                        if not isinstance(report_array, list):
                            report_array = []
                    if len(report_array) > MAX_FILE_REPORTS:
                        report_array = report_array[-MAX_FILE_REPORTS // FILE_REPORT_TRIM_DIVISOR :]
            except Exception:
                report_array = []
        else:
            report_array = []
        report_array.append(new_report)
        try:
            with open(output_path, "w") as f:
                json.dump(report_array, f, indent=LOCAL_REPORT_JSON_INDENT)
        except Exception:
            file_ok = False

    if output in ("http", "both"):
        ingest_payload = _build_ingest_payload(new_report)
        http_ok = _send_ingest(ingest_payload, report=report)

    if output == "file":
        return file_ok
    if output == "http":
        return http_ok
    return file_ok and http_ok
