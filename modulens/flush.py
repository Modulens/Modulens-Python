import os
import json

DEFAULT_OUTPUT_PATH = "modulens_output/runtime_report.json"

def merge_reports(existing: dict, new: dict) -> dict:
    # Init top-level keys if missing
    existing.setdefault("called_functions", {})
    existing.setdefault("defined_functions", [])
    existing.setdefault("duration_sec", 0)

    # Merge called functions
    for func, stats in new.get("called_functions", {}).items():
        if func in existing["called_functions"]:
            existing_stats = existing["called_functions"][func]
            existing_stats["count"] += stats["count"]
            existing_stats["total_time_sec"] += stats["total_time_sec"]
            existing_stats["avg_time_ms"] = round(
                1000.0 * existing_stats["total_time_sec"] / existing_stats["count"], 2
            )
        else:
            existing["called_functions"][func] = stats

    # Merge defined functions
    all_defined = set(existing.get("defined_functions", [])) | set(new.get("defined_functions", []))
    existing["defined_functions"] = sorted(all_defined)

    # Recalculate dead functions dynamically
    all_called = set(existing["called_functions"].keys())
    existing["dead_functions"] = sorted(all_defined - all_called)

    # Add duration
    existing["duration_sec"] += new.get("duration_sec", 0)

    return existing

def flush_data(payload: dict, report=True):
    os.makedirs(os.path.dirname(DEFAULT_OUTPUT_PATH), exist_ok=True)

    # Load and merge
    if os.path.exists(DEFAULT_OUTPUT_PATH):
        try:
            with open(DEFAULT_OUTPUT_PATH) as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    else:
        existing = {}

    merged = merge_reports(existing, payload)

    try:
        with open(DEFAULT_OUTPUT_PATH, "w") as f:
            json.dump(merged, f, indent=2)
        if report:
            print(f"[Modulens] ✅ Report saved to {DEFAULT_OUTPUT_PATH}")
            print(f"[Modulens] 🔍 {len(merged['called_functions'])} used functions")
            print(f"[Modulens] ⚰️  {len(merged['dead_functions'])} dead functions")
    except Exception as e:
        if report:
            print(f"[Modulens] ❌ Failed to write report: {e}")
