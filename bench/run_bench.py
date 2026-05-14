"""Modulens SDK benchmark runner.

Usage:
    python -m bench.run_bench
    python -m bench.run_bench --save baseline.json
    python -m bench.run_bench --compare baseline.json
    python -m bench.run_bench --only baseline_overhead,resolve_code_cache

This is intentionally stdlib-only; no pytest, no third-party benchmark deps.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from typing import Any, Dict, Iterable, Optional

# Allow running the file directly (python bench/run_bench.py) by ensuring the
# repo root is importable.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from bench import scenarios

REGRESSION_THRESHOLD_PCT = 15.0


def _select(names: Optional[Iterable[str]]) -> Dict[str, Any]:
    if not names:
        return dict(scenarios.ALL_SCENARIOS)
    selected = {}
    for name in names:
        if name not in scenarios.ALL_SCENARIOS:
            raise SystemExit(f"unknown scenario: {name!r}; choose from {sorted(scenarios.ALL_SCENARIOS)}")
        selected[name] = scenarios.ALL_SCENARIOS[name]
    return selected


def _run(selected: Dict[str, Any]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for name, fn in selected.items():
        print(f"running {name}...", flush=True)
        try:
            results[name] = fn()
        except Exception as e:  # benchmarks should not crash the whole run
            results[name] = {"error": repr(e)}
            print(f"  ERROR: {e!r}")
    return results


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.1f}"
        if abs(value) >= 10:
            return f"{value:,.2f}"
        return f"{value:,.4f}"
    return str(value)


def _print_results(results: Dict[str, Any]) -> None:
    for name, metrics in results.items():
        print(f"\n[{name}]")
        if "error" in metrics:
            print(f"  ERROR: {metrics['error']}")
            continue
        width = max(len(k) for k in metrics.keys())
        for k, v in metrics.items():
            print(f"  {k:<{width}}  {_format_value(v)}")


def _compare(current: Dict[str, Any], baseline: Dict[str, Any]) -> bool:
    """Print per-scenario deltas. Return True if any regression > threshold."""
    regressed = False
    print("\n=== comparison vs baseline ===")
    for name, current_metrics in current.items():
        baseline_metrics = baseline.get("scenarios", {}).get(name)
        if not baseline_metrics:
            print(f"\n[{name}]  (no baseline entry)")
            continue
        if "error" in current_metrics or "error" in baseline_metrics:
            print(f"\n[{name}]  skipped (errors)")
            continue
        print(f"\n[{name}]")
        width = max(len(k) for k in current_metrics.keys())
        for key, cur_value in current_metrics.items():
            base_value = baseline_metrics.get(key)
            if not isinstance(cur_value, (int, float)) or not isinstance(base_value, (int, float)):
                continue
            if base_value == 0:
                pct = float("inf") if cur_value else 0.0
            else:
                pct = ((cur_value - base_value) / base_value) * 100
            marker = ""
            # Treat "lower is better" for timing-style keys.
            if any(suffix in key for suffix in ("_ns", "_sec", "overhead_pct")):
                if pct > REGRESSION_THRESHOLD_PCT:
                    marker = "  !! regression"
                    regressed = True
                elif pct < -REGRESSION_THRESHOLD_PCT:
                    marker = "  ++ improvement"
            print(
                f"  {key:<{width}}  baseline={_format_value(base_value)}  "
                f"current={_format_value(cur_value)}  delta={pct:+.1f}%{marker}"
            )
    return regressed


def _env_block() -> Dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Modulens SDK benchmark runner")
    parser.add_argument("--save", metavar="PATH", help="write results to JSON (baseline)")
    parser.add_argument("--compare", metavar="PATH", help="compare current run against a saved JSON baseline")
    parser.add_argument(
        "--only",
        metavar="NAME,NAME,...",
        help="run only the listed scenarios (comma-separated)",
    )
    args = parser.parse_args()

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    selected = _select(only)

    results = _run(selected)
    _print_results(results)

    output = {"env": _env_block(), "scenarios": results}

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, sort_keys=True)
        print(f"\nsaved baseline to {args.save}")

    if args.compare:
        with open(args.compare, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        regressed = _compare(results, baseline)
        if regressed:
            print("\nFAIL: at least one regression above threshold.")
            return 1
        print("\nOK: no regression above threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
