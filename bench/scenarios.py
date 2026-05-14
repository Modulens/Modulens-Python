"""Microbenchmark scenarios for the Modulens SDK.

Each scenario returns a `dict` of measurements. Keep the surface narrow so
`run_bench.py` can serialize results to JSON and diff against a saved baseline.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
import timeit
import types
from typing import Any, Dict, List, Tuple

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


# -- realistic web-handler workload ----------------------------------------
#
# These helpers simulate the per-request call pattern of a small CRUD endpoint:
# parse query → validate → fetch user (with a sleep standing in for a DB hit)
# → permission check → build response → serialize. Each helper is a separate
# Python function so we generate a realistic number of `call`/`return` events
# per request without inflating the workload with synthetic recursion.
#
# Per-request Python-level call count is intentionally modest (~25 plus the
# per-item normalizations), in the same ballpark as a Flask/FastAPI handler
# once you exclude the framework's own C-implemented dispatch.


def _http_io_ms(ms: float) -> None:
    """Simulated synchronous I/O wait (DB round trip, external HTTP, etc.)."""
    if ms > 0:
        time.sleep(ms / 1000.0)


def _normalize(s: str) -> str:
    return s.strip().lower()


def _parse_kv(token: str) -> Tuple[str, str]:
    k, _, v = token.partition("=")
    return _normalize(k), _normalize(v)


def _parse_query(q: str) -> Dict[str, str]:
    return dict(_parse_kv(t) for t in q.split("&") if "=" in t)


def _validate_params(d: Dict[str, str], required: Tuple[str, ...]) -> bool:
    return all(k in d for k in required)


def _fetch_user(uid: str, io_ms: float) -> Dict[str, str]:
    _http_io_ms(io_ms)
    return {"id": uid, "role": "user", "name": "alice"}


def _check_perm(user: Dict[str, str], action: str) -> bool:
    return action in {"read", "list", "create"} and user["role"] != "banned"


def _build_items(uid: str, n: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(n):
        items.append({"id": i, "user": uid, "tag": _normalize(f"Item-{i}")})
    return items


def _serialize_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True).encode()


def _run_handler(*, io_ms: float, item_count: int = 10) -> bytes:
    body = "user_id=42&action=list&n=10"
    params = _parse_query(body)
    if not _validate_params(params, ("user_id", "action")):
        return b"invalid"
    user = _fetch_user(params["user_id"], io_ms)
    if not _check_perm(user, params["action"]):
        return b"forbidden"
    items = _build_items(user["id"], item_count)
    return _serialize_json({"user": user, "items": items})


# -- "heavy" variant: more functions, more items, more layers ------------
#
# Designed to approximate a realistic CRUD-with-ORM endpoint:
# parse → validate → fetch → enrich → permission → build N rich items
# (each item touches 3 helper functions) → paginate → audit → serialize.
# Per-request Python call count is roughly an order of magnitude higher than
# `_run_handler`, which is the realistic shape for a typical Flask/FastAPI
# handler that does meaningful work (ORM serialization, response shaping).


def _format_meta(i: int) -> Dict[str, Any]:
    return {"index": i, "label": _normalize(f"meta-{i}")}


def _build_item_rich(uid: str, i: int) -> Dict[str, Any]:
    return {
        "id": i,
        "user": uid,
        "tag": _normalize(f"Item-{i}"),
        "meta": _format_meta(i),
    }


def _build_items_rich(uid: str, n: int) -> List[Dict[str, Any]]:
    return [_build_item_rich(uid, i) for i in range(n)]


def _enrich_user(user: Dict[str, str]) -> Dict[str, str]:
    return {**user, "display_name": _normalize(user["name"]).title()}


def _audit_log(action: str, user_id: str) -> Dict[str, Any]:
    return {"event": _normalize(action), "user": user_id, "ts": 0}


def _compute_pagination(total: int, page_size: int) -> Dict[str, int]:
    return {"total": total, "pages": (total + page_size - 1) // page_size}


def _run_handler_heavy(*, io_ms: float, item_count: int = 50) -> bytes:
    body = "user_id=42&action=list&n=50"
    params = _parse_query(body)
    if not _validate_params(params, ("user_id", "action")):
        return b"invalid"
    user = _fetch_user(params["user_id"], io_ms)
    user = _enrich_user(user)
    if not _check_perm(user, params["action"]):
        return b"forbidden"
    items = _build_items_rich(user["id"], item_count)
    pagination = _compute_pagination(len(items), 10)
    audit = _audit_log(params["action"], user["id"])
    return _serialize_json(
        {"user": user, "items": items, "pagination": pagination, "audit": audit}
    )


def _count_python_events(fn, *args, **kwargs) -> int:
    """Count `call`+`return` profile events fired during one invocation of `fn`.

    CPython suppresses profile events while inside the profile callback itself,
    so the handler's own code does not pollute the count.
    """
    counter = [0]

    def handler(frame, event, arg):
        if event == "call" or event == "return":
            counter[0] += 1

    sys.setprofile(handler)
    try:
        fn(*args, **kwargs)
    finally:
        sys.setprofile(None)
    return counter[0]


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


def _bench_web_handler(
    *,
    label: str,
    handler,
    io_ms: float,
    trials: int = 5,
    requests_per_trial: int = 100,
) -> Dict[str, Any]:
    """Measure profiler overhead on a realistic CRUD-style handler.

    Important: the workload may include `time.sleep(io_ms)` per request. The
    sleep is a single C call, so it adds wallclock without adding profile
    events — same as real I/O. The percentage overhead therefore reflects how
    much the *Python-level* call cost dominates the request, not how accurately
    we can profile time inside the sleep.

    `events_per_request` is measured separately by running the handler once
    under a bare profile hook that just counts call/return events. From that
    we derive `ns_per_event`, which is the actually-fixed quantity across
    scenarios. If `ns_per_event` is stable across light vs heavy handlers,
    the linear-cost model holds.
    """
    _configure_quiet_output(fresh=True)
    prev_interval = cfg_module.config.get("flush_interval")
    cfg_module.config["flush_interval"] = 3600.0

    events_per_request = _count_python_events(handler, io_ms=io_ms)

    try:
        base_samples: List[float] = []
        for _ in range(trials):
            t0 = time.perf_counter()
            for _ in range(requests_per_trial):
                handler(io_ms=io_ms)
            base_samples.append(time.perf_counter() - t0)

        profiler = ModulensProfiler()
        try:
            profiler.start(include=["bench"])
            prof_samples: List[float] = []
            for _ in range(trials):
                t0 = time.perf_counter()
                for _ in range(requests_per_trial):
                    handler(io_ms=io_ms)
                prof_samples.append(time.perf_counter() - t0)
        finally:
            profiler.stop(report=False)
    finally:
        cfg_module.config["flush_interval"] = prev_interval

    base = statistics.median(base_samples)
    prof = statistics.median(prof_samples)
    overhead_pct = ((prof - base) / base) * 100 if base > 0 else float("nan")
    us_added_per_request = ((prof - base) / requests_per_trial) * 1e6
    ns_per_event = (
        (us_added_per_request * 1000) / events_per_request
        if events_per_request > 0
        else float("nan")
    )
    return {
        "label": label,
        "baseline_sec": base,
        "profiled_sec": prof,
        "overhead_pct": overhead_pct,
        "requests_per_trial": requests_per_trial,
        "io_ms_per_request": io_ms,
        "us_per_request_baseline": (base / requests_per_trial) * 1e6,
        "us_per_request_profiled": (prof / requests_per_trial) * 1e6,
        "us_added_per_request": us_added_per_request,
        "events_per_request": events_per_request,
        "ns_per_event": ns_per_event,
    }


def bench_web_handler_compute() -> Dict[str, Any]:
    """Light CRUD handler, no simulated I/O. ~25 Python calls / request."""
    return _bench_web_handler(
        label="Light CRUD handler, no I/O",
        handler=_run_handler,
        io_ms=0.0,
    )


def bench_web_handler_io_5ms() -> Dict[str, Any]:
    """Light CRUD endpoint with one fast DB hit."""
    return _bench_web_handler(
        label="Light CRUD handler, 5ms DB wait",
        handler=_run_handler,
        io_ms=5.0,
        requests_per_trial=40,
    )


def bench_web_handler_io_50ms() -> Dict[str, Any]:
    """Light handler, heavy-I/O endpoint (external API or slow query)."""
    return _bench_web_handler(
        label="Light handler, 50ms external call",
        handler=_run_handler,
        io_ms=50.0,
        requests_per_trial=15,
    )


def bench_web_handler_heavy_compute() -> Dict[str, Any]:
    """Heavy CRUD handler (ORM-style serialization), no I/O. Real worst case."""
    return _bench_web_handler(
        label="Heavy CRUD handler (50 rich items), no I/O",
        handler=_run_handler_heavy,
        io_ms=0.0,
        requests_per_trial=40,
    )


def bench_web_handler_heavy_io_20ms() -> Dict[str, Any]:
    """Heavy CRUD handler with 20ms total I/O — typical real-world endpoint."""
    return _bench_web_handler(
        label="Heavy CRUD handler (50 rich items), 20ms DB wait",
        handler=_run_handler_heavy,
        io_ms=20.0,
        requests_per_trial=25,
    )


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
    "web_handler_compute": bench_web_handler_compute,
    "web_handler_io_5ms": bench_web_handler_io_5ms,
    "web_handler_io_50ms": bench_web_handler_io_50ms,
    "web_handler_heavy_compute": bench_web_handler_heavy_compute,
    "web_handler_heavy_io_20ms": bench_web_handler_heavy_io_20ms,
    "resolve_code_cache": bench_resolve_code_cache,
    "serialize_variant": bench_serialize_variant,
    "feature_flag_decorator": bench_feature_flag_decorator,
    "recorder_record": bench_recorder_record,
    "flush_1000": lambda: bench_flush(n_functions=1000),
    "flush_data_file": bench_flush_data_file_only,
}
