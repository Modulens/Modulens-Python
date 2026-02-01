import os

config = {
    "include": [],
    "exclude": ["flask", "werkzeug", "gunicorn", "logging"],
    "flush_interval": float(os.getenv("MODULENS_FLUSH_INTERVAL", 30)),
    "api_url": os.getenv("MODULENS_API_URL", "").rstrip("/"),
    "api_key": os.getenv("MODULENS_API_KEY", ""),
    "project_id": os.getenv("MODULENS_PROJECT_ID", ""),
    "org_id": os.getenv("MODULENS_ORG_ID", ""),
    "environment": os.getenv("MODULENS_ENVIRONMENT", "production"),
    # "file" | "http" | "both" — where to send flush data
    "output": os.getenv("MODULENS_OUTPUT", "file").lower(),
}
