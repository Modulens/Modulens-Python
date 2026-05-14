# Modulens SDK benchmarks

Stdlib-only microbench harness for tracking SDK overhead across changes. Use this
before merging perf-sensitive refactors (hot-path locking, alternative recorders,
serialization changes, etc.).

## What is measured

| Scenario | Purpose |
| --- | --- |
| `baseline_overhead` | Recursive Fibonacci with vs without an installed profiler. **Worst-case** dense-recursion workload — useful for relative regression tracking only, *not* a representative overhead number. |
| `web_handler_compute` | Realistic CRUD-style handler (parse → validate → permission → list → serialize) with **no** simulated I/O. CPU-bound worst-case for real code. |
| `web_handler_io_5ms` | Same handler with a 5 ms simulated DB wait (`time.sleep`). Typical CRUD endpoint. |
| `web_handler_io_50ms` | Same handler with a 50 ms simulated external call. Heavy-I/O endpoint. |
| `resolve_code_cache` | Cache hit vs miss for `_resolve_code` — confirms the code-object-id cache is worth keeping. |
| `serialize_variant` | Per-type cost of `serialize_variant` (None, bool, int, float, short/long str, dict, list). |
| `feature_flag_decorator` | Cost added by wrapping a trivial function with `@feature_flag`. |
| `recorder_record` | Pure `FeatureFlagRecorder.record` cost, no decorator. |
| `flush_1000` | One `profiler.flush()` with 1,000 synthetic functions tracked. |
| `flush_data_file` | End-to-end `flush_data` with file sink only (no HTTP). |

Timing-style fields are in **nanoseconds per operation** unless they end in `_sec`.

## Running

```bash
# from repo root
python -m bench.run_bench

# save a baseline for later comparisons
python -m bench.run_bench --save bench/baselines/local.json

# compare against a saved baseline (exits non-zero on >15% regression)
python -m bench.run_bench --compare bench/baselines/local.json

# run only specific scenarios
python -m bench.run_bench --only baseline_overhead,resolve_code_cache
```

## Interpreting results

- **Single runs are noisy.** Each scenario uses `timeit.Timer.autorange()` and
  takes a median of multiple trials, but Windows / virtualized environments can
  still skew results by 5–10 %. The harness flags regressions above **15 %**.
- **`ns_per_event` is the fundamental metric.** Across our handlers it sits
  around **~1,100 ns per profile event** (one `call` event + one `return` event
  per Python function call, so ~2.2 µs per call). This number stays roughly
  constant across light and heavy handlers — verified by `ns_per_event` being
  ~1,097 ns on `web_handler_heavy_compute` (466 events/req) and ~1,116 ns on
  `web_handler_compute` (76 events/req).
- **`us_added_per_request` is `events_per_request × ns_per_event`.** It scales
  linearly with how much Python the request does. There is no "fixed
  per-request cost"; previous versions of this README claimed otherwise and
  were wrong.
- **`web_handler_heavy_io_20ms` is the most defensible "real CRUD endpoint"
  number** — ~466 events per request, 20 ms total wallclock. Current
  measurement on this branch: **~2.9 % overhead**. That is what a typical
  Flask/FastAPI endpoint with ORM serialization will pay.
- **`web_handler_io_5ms.overhead_pct`** (the *light* synthetic, 76 events,
  5 ms) currently lands around 1.7 %. This applies to lean handlers and is
  not representative of a CRUD handler with response shaping.
- **Compute-bound scenarios** (`*_compute`) measure the worst case where the
  request does pure Python work with no I/O. Expect 500–700 % overhead. This
  is a fundamental limitation of `sys.setprofile`-based profilers and only
  changes with an architecture rewrite (sampling, `sys.monitoring`, or
  opt-in instrumentation).
- **`baseline_overhead.overhead_pct` (fib)** is a regression tracker, not a
  publishable number. It's the worst case the harness can produce.
- **`resolve_code_cache.miss_over_hit_ratio`** documents the value of the
  per-code-object cache. A high ratio means the cache is doing real work.
- **`feature_flag_decorator.overhead_ns`** is the only number that matters for
  the decorator path on hot code. Below ~1 µs per call is fine for most apps.

## Mapping overhead to your workload

The cost model that actually holds:

```
overhead_per_request_µs ≈ python_calls_per_request × 2 × 1.1 µs
                       = python_calls_per_request × 2.2 µs

overhead_pct ≈ overhead_per_request_µs / total_request_time_µs
```

To find `python_calls_per_request` for your own handler, run it briefly under
`cProfile` or `sys.setprofile` and count `call` events. Or use Modulens itself
for one flush window and read `defined_functions` × actual invocations.

Realistic mapping (using the measured ~2.2 µs per Python call):

| Calls / req | Profiler adds | At 10 ms wall | At 50 ms wall | At 100 ms wall |
|---:|---:|---:|---:|---:|
| 25  (toy)             |   ~55 µs |     0.55 % |     0.11 % |     0.06 % |
| 75  (lean handler, our `web_handler_*`) |  ~165 µs |    **1.7 %** |     0.33 % |     0.17 % |
| 250 (typical CRUD w/ ORM)               |  ~550 µs |    **5.5 %** |    **1.1 %** |     0.55 % |
| 500 (heavy serialization, our `*_heavy`) | ~1.1 ms |     **11 %** |    **2.2 %** |    **1.1 %** |
| 1000 (very chatty handler)             |   ~2.2 ms |     **22 %** |    **4.4 %** |    **2.2 %** |

The takeaway: **`<1 %` is a property of your specific handler, not the
profiler.** It holds when `python_calls_per_request × 2.2 µs` is less than
1 % of your total request time. For a CRUD endpoint with 250 Python calls and
50 ms wall time, you're already over 1 %. For 100 ms wall time, you're at it.
For sub-10 ms compute paths, you cannot get there with this architecture.

The honest README claim should be something like: *"Typical overhead is 1–5 %
on web handlers doing 10–100 ms of work, dominated by per-Python-call cost.
Disable or use selective instrumentation on tight compute paths."*

## When to update the baseline

Refresh `bench/baselines/local.json` after intentional perf changes that you
expect to shift numbers. Note the change in the PR description.

## What the harness has already caught

The first end-to-end run of `bench/run_bench.py` surfaced a real SDK bug:
`flush()` ran with `sys.setprofile` still attached, so every nested call inside
`inspect.getmembers`, `json.dump`, and the file/HTTP sinks re-entered
`_profile_handler` and paid quadratic overhead. The fix (suspending the hook
for the duration of `flush()`) ships in the same PR as this harness, along
with a regression test in `tests/test_profiler.py::FlushSuspendsProfileHookTests`.

Lesson: do not assume "the SDK is fast" without measurement. The benchmarks
exist precisely to catch this class of issue before it ships.

## Caveats

- These are **microbenchmarks**. They do not exercise multi-thread contention,
  multi-process startup costs, or real HTTP ingest latency.
- The harness does not pin CPU affinity or enable RT scheduling. CI runs will be
  noisier than a quiet laptop; do not gate merges on absolute numbers, only on
  large relative regressions.
- `sys.setprofile` is global. Scenarios that install a profiler stop it before
  returning; if a scenario crashes mid-run, you may have a stale profile hook
  installed — open a fresh interpreter.
