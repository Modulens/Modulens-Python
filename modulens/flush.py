import os
import json
import time
import urllib.request
import urllib.error

from .config import config

DEFAULT_OUTPUT_PATH = "modulens_output/runtime_report.json"
INGEST_ENDPOINT = "/ingest"
MAX_HTTP_RETRIES = 2
HTTP_RETRY_DELAY_SEC = 1.0


def _build_report(payload: dict) -> dict:
    """Build report dict (timestamp, called_functions, dead_functions) from profiler payload."""
    new_report = {
        "timestamp": int(time.time()),
        "called_functions": {},
        "dead_functions": sorted(payload.get("dead_functions", [])),
    }
    for func, stats in payload.get("called_functions", {}).items():
        count = stats.get("count", 0)
        total_time = stats.get("total_time_sec", 0.0)
        avg_time = round(1000.0 * total_time / count, 2) if count else 0.0
        new_report["called_functions"][func] = {
            "count": count,
            "avg_time_ms": avg_time,
        }
    return new_report


def _build_ingest_payload(report: dict) -> dict:
    """Build backend SnapshotInput payload (project_id, org_id, environment, etc.)."""
    try:
        org_id = config.get("org_id")
        if isinstance(org_id, str) and org_id.isdigit():
            org_id = int(org_id)
        elif not isinstance(org_id, int):
            org_id = 0
    except Exception:
        org_id = 0

    return {
        "timestamp": report["timestamp"],
        "environment": config.get("environment", "production"),
        "project_id": config.get("project_id", ""),
        "org_id": org_id,
        "called_functions": report["called_functions"],
        "dead_functions": report["dead_functions"],
    }


def _send_ingest(payload: dict, report: bool) -> bool:
    """POST payload to Modulens ingest API. Returns True on success."""
    api_url = (config.get("api_url") or "").strip()
    api_key = (config.get("api_key") or "").strip()
    project_id = (config.get("project_id") or "").strip()
    try:
        org_id = int(payload.get("org_id", 0) or 0)
    except (TypeError, ValueError):
        org_id = 0
    if not api_url or not api_key or not project_id or org_id <= 0:
        if report:
            print("[Modulens] ⏭️  Skipping HTTP ingest (set MODULENS_API_URL, MODULENS_API_KEY, MODULENS_PROJECT_ID, MODULENS_ORG_ID for E2E)")
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
            with urllib.request.urlopen(req, timeout=30) as resp:
                if 200 <= resp.status < 300:
                    if report:
                        print("[Modulens] ✅ Ingest sent to Modulens")
                    return True
                last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if e.code and 400 <= e.code < 500 and e.code != 429:
                break  # no retry on client errors
        except urllib.error.URLError as e:
            last_error = str(e.reason or e)
        except Exception as e:
            last_error = str(e)
        if attempt < MAX_HTTP_RETRIES:
            time.sleep(HTTP_RETRY_DELAY_SEC * (attempt + 1))

    if report:
        print(f"[Modulens] ❌ Ingest failed: {last_error}")
    return False


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
        os.makedirs(os.path.dirname(DEFAULT_OUTPUT_PATH), exist_ok=True)
        if os.path.exists(DEFAULT_OUTPUT_PATH):
            try:
                with open(DEFAULT_OUTPUT_PATH, "r") as f:
                    report_array = json.load(f)
                    if not isinstance(report_array, list):
                        report_array = []
            except Exception:
                report_array = []
        else:
            report_array = []
        report_array.append(new_report)
        try:
            with open(DEFAULT_OUTPUT_PATH, "w") as f:
                json.dump(report_array, f, indent=2)
            if report:
                print(f"[Modulens] ✅ Appended new flush to {DEFAULT_OUTPUT_PATH}")
                print(f"[Modulens] 🔍 {len(new_report['called_functions'])} used functions")
                print(f"[Modulens] ⚰️  {len(new_report['dead_functions'])} dead functions")
        except Exception as e:
            if report:
                print(f"[Modulens] ❌ Failed to write report: {e}")
            file_ok = False

    if output in ("http", "both"):
        ingest_payload = _build_ingest_payload(new_report)
        http_ok = _send_ingest(ingest_payload, report=report)

    return file_ok and http_ok
