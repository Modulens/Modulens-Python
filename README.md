# Modulens

[![PyPI version](https://img.shields.io/pypi/v/modulens.svg)](https://pypi.org/project/modulens/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://pypi.org/project/modulens/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Know what your Python code is doing.** Modulens is a lightweight profiler that tracks every function call, finds dead code, catches errors at the source — and opens GitHub PRs to clean up what's unused. Works with Flask, FastAPI, Django, Celery, or any Python app.

> Two lines of code. No config files. No agents.

## Why Modulens?

- **Dead code detection** — finds functions that are defined but never called in production
- **Auto dead-code PRs** — connects to GitHub and opens pull requests to remove unused functions
- **Per-function error tracking** — counts exceptions at the originating function, not just the handler
- **Performance metrics** — call counts, total runtime, and average execution time per function
- **Dependency graphs** — visualize how your modules and functions depend on each other
- **Low production overhead** — typically 1–3 % on web handlers; built on Python's native `sys.setprofile` with configurable sampling for tighter budgets

## Quick Start

```bash
pip install modulens
```

```python
import modulens

modulens.start(include=['app'])
# That's it. Deploy your app and check the dashboard.
```

### Flask

```python
from flask import Flask
import modulens

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello, World!"

if __name__ == "__main__":
    modulens.start(include=['app'])
    app.run()
```

### FastAPI

```python
from fastapi import FastAPI
import modulens

app = FastAPI()

modulens.start(include=['app'])

@app.get("/")
def root():
    return {"message": "Hello, World!"}
```

### Django

In your `manage.py` or `wsgi.py`:

```python
import modulens
modulens.start(include=['myproject', 'myapp'])
```

## Send Data to the Dashboard

Modulens defaults to sending data over HTTP to `https://modulens-backend.onrender.com`. Set your API key and project ID (from the dashboard) and you're done:

```bash
MODULENS_API_KEY=ml_xxxx
MODULENS_PROJECT_ID=your-project-slug
```

Optional: `MODULENS_API_URL` (default: `https://modulens-backend.onrender.com`), `MODULENS_OUTPUT` (default: `http`), `MODULENS_ENVIRONMENT` (default: `production`).

Then visit [dashboard.modulens.io](https://dashboard.modulens.io) to see live function metrics, dead code, error counts, and dependency graphs.

## Local-Only Mode

Set `MODULENS_OUTPUT=file` (and don't set `MODULENS_API_KEY` / `MODULENS_PROJECT_ID`) and Modulens writes to a local JSON file instead:

```
modulens_output/runtime_report.json
```

Use `MODULENS_OUTPUT=both` to write locally and send to the API at the same time.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MODULENS_FLUSH_INTERVAL` | Seconds between auto-flushes | `60` |
| `MODULENS_OUTPUT` | `file`, `http`, or `both` | `http` |
| `MODULENS_API_URL` | Backend ingest URL | `https://modulens-backend.onrender.com` |
| `MODULENS_API_KEY` | Project API key | — |
| `MODULENS_PROJECT_ID` | Project slug from dashboard | — |
| `MODULENS_ENVIRONMENT` | e.g. `production`, `staging` | `production` |
| `MODULENS_FEATURE_FLAG_MAX_VARIANT_LEN` | Max characters per serialized variant bucket | `128` |
| `MODULENS_FEATURE_FLAG_MAX_DISTINCT_VARIANTS` | Max distinct buckets per flag/function per flush window | `64` |

### Programmatic Options

```python
modulens.start(
    include=['app'],       # Module prefixes to track
    exclude=['app.tests'], # Module prefixes to ignore
    sample_rate=0.1        # 10% sampling for high-traffic apps
)
```

## API

| Function | Description |
|----------|-------------|
| `modulens.start(include, exclude, sample_rate)` | Start profiling. Registers exit hook and background flush. |
| `modulens.flush(report=True)` | Flush current metrics now. Resets counters for the next interval. |
| `modulens.stop(report=True)` | Stop profiling, final flush, clean up. Safe to call multiple times. |
| `modulens.feature_flag(name=None)` | Decorate a function to record successful return values as feature-flag variants. |

### Feature flags

Wrap functions that return flag outcomes (booleans, strings, enums, small JSON-serializable values). Each successful return is serialized into a bucket and counted until the next flush. **Exceptions are not counted.**

```python
import modulens

@modulens.feature_flag("new_checkout_ui")
def get_checkout_config():
    return True
```

Omit the name to use the function name as the flag key. Variants are capped for payload size (`MODULENS_FEATURE_FLAG_MAX_VARIANT_LEN`, `MODULENS_FEATURE_FLAG_MAX_DISTINCT_VARIANTS`). Flushes include a `feature_flags` array on local reports and on ingest when present.

## How It Works

Modulens uses Python's `sys.setprofile` to intercept function calls and returns at the interpreter level. It tracks call counts, durations, and exceptions per function, then flushes snapshots on a configurable interval. The dashboard aggregates these into trends, detects dead code by comparing defined vs. called functions, and can open GitHub PRs to remove the dead ones.

### Overhead and accuracy

Modulens adds roughly 2 µs per Python function call (one `call` event + one `return` event at about 1.1 µs each, measured on CPython 3.12). For a typical Flask/FastAPI request making 200–500 Python calls in 20–100 ms of wallclock, that works out to 0.5–5 % overhead — within the normal noise of GC pauses and neighboring traffic. See [`bench/`](bench/README.md) for the harness and a workload-to-overhead mapping table.

Two caveats worth knowing:

- **Tight pure-CPU paths** (sub-millisecond requests that do no I/O) will see much higher overhead because per-event cost dominates. Use `sample_rate=0.1` or wrap those paths with explicit `modulens.stop()` / `modulens.start()`.
- **Per-function timings below ~10 µs are dominated by profiler overhead** and should be treated as upper bounds. Modulens is built to find your slow handlers and dead code, not to micro-benchmark microsecond-level helpers — reach for `timeit` or `cProfile` for that.

## Requirements

- Python 3.8+
- No external dependencies for core profiling
- Works with any Python framework or plain scripts

## Links

- [Dashboard](https://dashboard.modulens.io)
- [Documentation](https://modulens.io/docs)
- [PyPI](https://pypi.org/project/modulens/)

## License

MIT — see [LICENSE](LICENSE) for details.
