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
  still skew results by 5–10%. The harness flags regressions above **15%**.
- **`web_handler_io_5ms.overhead_pct` is the number to publish.** It reflects
  a realistic CRUD endpoint with one fast DB hit. Current measurement on this
  branch: **~0.66 %**. This is what supports the README "low overhead" claim.
- **`web_handler_compute.overhead_pct` is the worst-case real-code number** —
  pure CPU work, no I/O. Current measurement: ~550 %. Any caller running tight
  pure-Python compute loops should disable Modulens for that path. This is a
  fundamental limitation of `sys.setprofile`-based profilers, not a bug.
- **`baseline_overhead.overhead_pct` (fib) is a regression tracker, not a
  publishable number.** It's the worst case the harness can produce; useful
  for spotting per-event-cost regressions, not for marketing.
- **`*.us_added_per_request`** is the additive Python-call cost the profiler
  imposes per request. For realistic handlers it lands around 80–100 µs. That
  number is independent of I/O time, which is why I/O-bound endpoints stay
  under 1 % overhead and CPU-bound endpoints don't.
- **`resolve_code_cache.miss_over_hit_ratio`** documents the value of the
  per-code-object cache. A high ratio means the cache is doing real work.
- **`feature_flag_decorator.overhead_ns`** is the only number that matters for
  the decorator path on hot code. Below ~1 µs per call is fine for most apps.

## Mapping overhead to your workload

The profiler's per-request cost is roughly fixed (~80–100 µs of added Python
work for a small handler, scaling roughly linearly with the number of Python
function calls in the request). The percentage overhead therefore depends
almost entirely on what *else* the request is doing:

```
overhead_pct ≈ python_overhead_per_request / total_request_time
            ≈ 90 µs / total_request_time_in_µs
```

| Total request time | Approx overhead |
|---|---|
| 100 µs (tight compute loop) | 90 % |
| 1 ms | ~9 % |
| 10 ms (typical fast endpoint) | ~0.9 % |
| 100 ms (slow endpoint / external call) | ~0.09 % |

If you need `<1 %` on a sub-millisecond request, the current
`sys.setprofile`-based architecture cannot deliver it. Options are documented
in the PR description.

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
