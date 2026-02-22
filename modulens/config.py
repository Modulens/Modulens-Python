import os

def _safe_float(val, default):
    try:
        result = float(val)
        return result if result > 0 else default
    except (TypeError, ValueError):
        return default

config = {
    "include": [],
    "exclude": ["flask", "werkzeug", "gunicorn", "logging"],
    "flush_interval": _safe_float(os.getenv("MODULENS_FLUSH_INTERVAL"), 30.0),
    "api_url": os.getenv("MODULENS_API_URL", "").rstrip("/"),
    "api_key": os.getenv("MODULENS_API_KEY", ""),
    "project_id": os.getenv("MODULENS_PROJECT_ID", ""),
    "org_id": os.getenv("MODULENS_ORG_ID", ""),
    "environment": os.getenv("MODULENS_ENVIRONMENT", "production"),
    "output": os.getenv("MODULENS_OUTPUT", "file").lower(),
}
