import os

config = {
    "include": [],
    "exclude": ["flask", "werkzeug", "gunicorn", "logging"],
    "flush_interval": float(os.getenv("MODULENS_FLUSH_INTERVAL", 10)),
}
