"""Microbenchmark scenarios for the Modulens SDK.

Each scenario returns a `dict` of measurements. Keep the surface narrow so
`run_bench.py` can serialize results to JSON and diff against a saved baseline.
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
import timeit
import types
from typing import Any, Dict, List

from modulens import config as cfg_module
from modulens import feature_flag
from modulens.feature_flags import (
    FeatureFlagRecorder,
    default_recorder,
    serialize_variant,
)
from modulens.flush import flush_data
from modulens.profiler import ModulensProfiler


# -- helpers ---------------------------------------------------------------


def _ns(seconds_per_op: float) -> float:
    return seconds_per_op * 1e9


def _autorange(stmt, *, globals=None, setup="pass", trials: int = 5) -> float:
    """Return median seconds-per-op across `trials` autorange runs.

    Each run picks its own iteration count via `Timer.autorange()` so the total
    wall time is at least ~0.2s and noise is bounded.
    """
    timer = timeit.Timer(stmt, setup=setup, globals=globals)
    samples: List[float] = []
    for _ in range(trials):
        number, elapsed = timer.autorange()
        samples.append(elapsed / number)
    return statistics.median(samples)


def _make_frame_like(modname: str, filename: str, name: str = "fn") -> Any:
    code = types.SimpleNamespace(co_filename=filename, co_name=name)
    return types.SimpleNamespace(f_code=code, f_globals={"__name__": modname})


def _configure_quiet_output(*, fresh: bool = True) -> str:
    """Force the profiler to write to a throwaway file so flushes are cheap.

    When `fresh=True` we delete any pre-existing file at the path; otherwise
    long-running benches will accumulate hundreds of MB of runtime reports
    that dominate every subsequent `flush_data` measurement.
    """
    path = os.path.join(tempfile.gettempdir(), "modulens_bench_runtime_report.json")
    if fresh and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    cfg_module.config["output"] = "file"
    cfg_module.config["output_path"] = path
    return path


# -- workload (used by baseline overhead scenario) -------------------------


def workload_fib(n: int = 14) -> int:
    if n <= 1:
        return n
    return workload_fib(n - 1) + workload_fib(n - 2)


def workload_loop(iterations: int = 500) -> int:
    total = 0
    for i in range(iterations):
        total += _workload_inner(i)
    return total


def _workload_inner(x: int) -> int:
    return (x * x) ^ (x >> 1)


# -- scenarios -------------------------------------------------------------


def bench_baseline_overhead(*, trials: int = 5, iterations: int = 5) -> Dict[str, float]:
    """Recursive Fibonacci with vs without an installed profiler.

    Workload is intentionally modest (~3k profiled events per trial) so the bench
    completes in seconds on CI and laptops, while still being dense enough to
    show profiler overhead.
    """
    _configure_quiet_output()
    # Park the background flush thread far away; we never want it firing mid-run.
    prev_interval = cfg_module.config.get("flush_interval")
    cfg_module.config["flush_interval"] = 3600.0

    base_samples: List[float] = []
    for _ in range(trials):
        t0 = time.perf_counter()
        for _ in range(iterations):
            workload_fib()
        base_samples.append(time.perf_counter() - t0)

    profiler = ModulensProfiler()
    try:
        profiler.start(include=["bench"])
        try:
            profiled_samples: List[float] = []
            for _ in range(trials):
                t0 = time.perf_counter()
                for _ in range(iterations):
                    workload_fib()
                profiled_samples.append(time.perf_counter() - t0)
        finally:
            profiler.stop(report=False)
    finally:
        cfg_module.config["flush_interval"] = prev_interval

    base = statistics.median(base_samples)
    profiled = statistics.median(profiled_samples)
    overhead_pct = ((profiled - base) / base) * 100 if base > 0 else float("nan")
    return {
        "baseline_sec": base,
        "profiled_sec": profiled,
        "overhead_pct": overhead_pct,
        "workload": f"fib(14) x {iterations}",
    }


def bench_resolve_code_cache(*, trials: int = 5, frames: int = 5_000) -> Dict[str, float]:
    """Compare cache-hit vs cache-miss for `_resolve_code`.

    `timeit.Timer.autorange` runs `setup` once per timing call (not per iter),
    so we cannot use it to force a cold cache every iteration. Instead, we
    construct N unique frame objects (each with its own `code`); after a single
    clear, all N lookups are misses, and a second pass over the same list is
    all hits.
    """
    prof = ModulensProfiler()
    prof._is_third_party_or_stdlib = lambda fn: False  # type: ignore[assignment]
    prof._included_tuple = ()  # accept everything
    frame_list = [
        _make_frame_like("bench.scenarios", __file__, f"workload_{i}")
        for i in range(frames)
    ]

    hit_samples: List[float] = []
    miss_samples: List[float] = []
    for _ in range(trials):
        prof._code_track_cache.clear()
        prof._code_key_cache.clear()
        prof._track_cache.clear()

        t0 = time.perf_counter()
        for f in frame_list:
            prof._resolve_code(f)
        miss_samples.append((time.perf_counter() - t0) / frames)

        t0 = time.perf_counter()
        for f in frame_list:
            prof._resolve_code(f)
        hit_samples.append((time.perf_counter() - t0) / frames)

    hit_sec = statistics.median(hit_samples)
    miss_sec = statistics.median(miss_samples)
    return {
        "cache_hit_ns": _ns(hit_sec),
        "cache_miss_ns": _ns(miss_sec),
        "miss_over_hit_ratio": miss_sec / hit_sec if hit_sec > 0 else float("nan"),
    }


def bench_serialize_variant(*, trials: int = 3) -> Dict[str, float]:
    """Per-type cost of variant serialization."""
    cases: Dict[str, Any] = {
        "none": None,
        "bool": True,
        "int": 42,
        "float": 3.14,
        "short_str": "variant_a",
        "long_str": "x" * 200,
        "dict": {"b": 2, "a": 1},
        "list": [1, 2, 3],
    }
    out: Dict[str, float] = {}
    for label, value in cases.items():
        sec = _autorange(
            "serialize_variant(v)",
            globals={"serialize_variant": serialize_variant, "v": value},
            trials=trials,
        )
        out[f"{label}_ns"] = _ns(sec)
    return out


def bench_feature_flag_decorator(*, trials: int = 5) -> Dict[str, float]:
    """Cost added by `@feature_flag` on a trivial function."""

    def bare() -> str:
        return "on"

    @feature_flag("bench_flag")
    def wrapped() -> str:
        return "on"

    default_recorder.clear()

    bare_sec = _autorange("fn()", globals={"fn": bare}, trials=trials)
    wrapped_sec = _autorange("fn()", globals={"fn": wrapped}, trials=trials)

    return {
        "bare_ns": _ns(bare_sec),
        "wrapped_ns": _ns(wrapped_sec),
        "overhead_ns": _ns(wrapped_sec - bare_sec),
    }


def bench_recorder_record(*, trials: int = 5) -> Dict[str, float]:
    """Pure recorder cost without decorator/function call overhead."""
    recorder = FeatureFlagRecorder()
    sec = _autorange(
        'recorder.record("flag", "fn", "v")',
        globals={"recorder": recorder},
        trials=trials,
    )
    return {"record_ns": _ns(sec)}


def bench_flush(*, n_functions: int = 1000) -> Dict[str, float]:
    """`flush()` with N synthetic functions; file output to a fresh temp path."""
    _configure_quiet_output(fresh=True)
    prof = ModulensProfiler()
    for i in range(n_functions):
        key = f"bench.mod.fn_{i}"
        prof.call_counts[key] = (i % 7) + 1
        prof.call_durations[key] = 0.0001 * (i % 13)

    t0 = time.perf_counter()
    prof.flush(report=False)
    elapsed = time.perf_counter() - t0
    return {"n_functions": n_functions, "flush_sec": elapsed}


def bench_flush_data_file_only(*, trials: int = 5) -> Dict[str, float]:
    """End-to-end `flush_data` cost with file sink only (no HTTP).

    Resets the output file before each trial so the measurement reflects the
    cost of building+writing one report, not the cost of re-serializing every
    prior report in the file.
    """
    path = _configure_quiet_output(fresh=True)
    payload = {
        "called_functions": {
            f"bench.fn_{i}": {"count": i + 1, "total_time_sec": 0.001 * i}
            for i in range(200)
        },
        "dead_functions": [f"bench.dead_{i}" for i in range(50)],
        "error_counts": {},
        "feature_flags": [],
    }
    samples: List[float] = []
    for _ in range(trials):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        t0 = time.perf_counter()
        flush_data(payload, report=False)
        samples.append(time.perf_counter() - t0)
    return {"flush_data_ns": _ns(statistics.median(samples))}


ALL_SCENARIOS = {
    "baseline_overhead": bench_baseline_overhead,
    "resolve_code_cache": bench_resolve_code_cache,
    "serialize_variant": bench_serialize_variant,
    "feature_flag_decorator": bench_feature_flag_decorator,
    "recorder_record": bench_recorder_record,
    "flush_1000": lambda: bench_flush(n_functions=1000),
    "flush_data_file": bench_flush_data_file_only,
}
