# Modulens Python SDK

Lightweight profiler for Python applications: track function calls, runtimes, and dead code with minimal overhead. Works with any Python framework (Flask, Django, FastAPI, Celery, or plain Python).

## Quick start

```python
import modulens

modulens.start(include=["app"])  # only track modules whose name starts with "app"
# ... run your app ...
modulens.flush()  # optional: flush now (otherwise auto-flush on interval and at exit)
```

## Configuration

### Include / exclude / sampling

- **`include`** — List of module name prefixes to track (e.g. `["app"]`). Recommended to avoid stdlib/third‑party noise.
- **`exclude`** — Additional prefixes to ignore (default includes `flask`, `werkzeug`, `gunicorn`, `logging`).
- **`sample_rate`** — 0.0–1.0; 1.0 = 100% of calls (default), lower for high‑traffic apps.

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MODULENS_FLUSH_INTERVAL` | Seconds between auto-flushes | `30` |
| `MODULENS_OUTPUT` | Where to send data: `file`, `http`, or `both` | `file` |
| `MODULENS_API_URL` | Modulens ingest API base URL (e.g. `https://api.modulens.io`) | — |
| `MODULENS_API_KEY` | Project API key (from Modulens dashboard) | — |
| `MODULENS_PROJECT_ID` | Project ID (slug) from dashboard | — |
| `MODULENS_ORG_ID` | Organization ID (number) | — |
| `MODULENS_ENVIRONMENT` | Environment name (e.g. `production`, `staging`) | `production` |

### E2E: send data to the Modulens dashboard

1. In the [Modulens dashboard](https://dashboard.modulens.io), create or open a project and copy **Project ID** and **Org ID**.
2. Generate an **API key** for the project (e.g. Project Settings).
3. Set in your environment (or `.env`):

   ```bash
   MODULENS_API_URL=https://your-backend.example.com
   MODULENS_API_KEY=ml_xxxx
   MODULENS_PROJECT_ID=your-project-slug
   MODULENS_ORG_ID=1
   MODULENS_ENVIRONMENT=production
   MODULENS_OUTPUT=http
   ```

4. Run your app. The SDK will POST snapshots to the ingest API on each flush (interval + at exit). Data appears in the dashboard.

Use `MODULENS_OUTPUT=both` to keep writing to `modulens_output/runtime_report.json` and send to the API.

## Local-only (file output)

If you do **not** set `MODULENS_API_URL` / `MODULENS_API_KEY` / `MODULENS_PROJECT_ID`, the SDK only writes to:

- **`modulens_output/runtime_report.json`** — Array of snapshots (timestamp, called_functions, dead_functions).

## API

- **`modulens.start(include=None, exclude=None, sample_rate=1.0)`** — Start profiling. Registers atexit flush and a background flush loop.
- **`modulens.flush(report=True)`** — Flush current stats now (to file and/or ingest). Resets in-memory counts so the next flush is for the next interval.
- **`modulens.stop(report=True)`** — Stop profiling: final flush, stop the flush loop, remove the profiler from the interpreter, and unregister the atexit handler. Safe to call multiple times; no-op if not started. You can call `start()` again after `stop()`.

## Requirements

- Python 3.8+
- No framework lock-in; works with Flask, Django, FastAPI, Celery, or any Python app.
