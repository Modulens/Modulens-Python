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
- **Under 1% overhead** — built on Python's native `sys.setprofile` with configurable sampling

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

Set these environment variables and Modulens will stream function metrics to your dashboard automatically:

```bash
MODULENS_API_URL=https://your-backend.example.com
MODULENS_API_KEY=ml_xxxx
MODULENS_PROJECT_ID=your-project-slug
MODULENS_ORG_ID=1
MODULENS_OUTPUT=http
MODULENS_ENVIRONMENT=production
```

Then visit [dashboard.modulens.io](https://dashboard.modulens.io) to see live function metrics, dead code, error counts, and dependency graphs.

## Local-Only Mode

Don't set any API variables and Modulens writes to a local JSON file instead:

```
modulens_output/runtime_report.json
```

Use `MODULENS_OUTPUT=both` to write locally and send to the API at the same time.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MODULENS_FLUSH_INTERVAL` | Seconds between auto-flushes | `30` |
| `MODULENS_OUTPUT` | `file`, `http`, or `both` | `file` |
| `MODULENS_API_URL` | Backend ingest URL | — |
| `MODULENS_API_KEY` | Project API key | — |
| `MODULENS_PROJECT_ID` | Project slug from dashboard | — |
| `MODULENS_ORG_ID` | Organization ID | — |
| `MODULENS_ENVIRONMENT` | e.g. `production`, `staging` | `production` |

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

## How It Works

Modulens uses Python's `sys.setprofile` to intercept function calls and returns at the interpreter level. It tracks call counts, durations, and exceptions per function, then flushes snapshots on a configurable interval. The dashboard aggregates these into trends, detects dead code by comparing defined vs. called functions, and can open GitHub PRs to remove the dead ones.

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
