# Modulens SDK benchmarks

Stdlib-only microbench harness for tracking SDK overhead across changes. Use this
before merging perf-sensitive refactors (hot-path locking, alternative recorders,
serialization changes, etc.).

## What is measured

| Scenario | Purpose |
| --- | --- |
| `baseline_overhead` | Recursive Fibonacci with vs without an installed profiler. The headline "what does Modulens cost?" number. |
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
- **`baseline_overhead.overhead_pct` is the marketing-relevant number.** The
  current README claims `<1% overhead`. That claim refers to typical web app
  request handling, **not** the worst-case `fib(18) x 20` workload here, which
  is dense user-space function calls — exactly where `sys.setprofile` hurts most.
  Treat this as a relative comparison metric across SDK versions, not as a
  general overhead estimate.
- **`resolve_code_cache.miss_over_hit_ratio`** documents the value of the
  per-code-object cache. A high ratio means the cache is doing real work.
- **`feature_flag_decorator.overhead_ns`** is the only number that matters for
  the decorator path on hot code. Below ~1 µs per call is fine for most apps.

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
